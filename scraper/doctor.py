"""Preflight check: does every selector still match live Google Maps?

No scraper against Google can be guaranteed to work forever — Google rotates
its obfuscated CSS classes on its own release cadence. What this gives you is
the next best thing: a 30-second answer to "is the markup still what we think
it is, or is something actually blocking me?" — two problems that look
identical from an empty CSV but need completely different fixes.
"""

import logging

from rich.markup import escape
from rich.table import Table

from config import settings
from config.runconfig import RunConfig
from geo.models import SearchUnit
from scraper.anti_detect import detail_delay, human_click, is_blocked
from scraper.browser import BrowserManager
from scraper.extract import extract_detail
from scraper.maps_scraper import collect_result_hrefs, css_attr_escape, wait_for_detail_panel
from scraper.scroll import find_feed_selector, find_result_selector, scroll_results
from scraper.selectors import CRITICAL_SELECTOR_KEYS, SELECTORS
from ui.console import console

logger = logging.getLogger(__name__)

# Selectors only present once a business detail panel is open.
_DETAIL_KEYS = [
    "detail_panel", "detail_name", "detail_address", "detail_phone",
    "detail_email", "detail_website", "detail_plus_code", "detail_hours",
    "detail_rating", "detail_reviews_count", "detail_category",
    "detail_claim", "detail_loaded",
]
_LIST_KEYS = ["results_feed", "result_link", "search_box", "end_of_list"]


async def _first_matching(page, key: str) -> tuple[str | None, int]:
    """Return (selector that matched, count) for a selector chain."""
    for sel in SELECTORS[key]:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                return sel, count
        except Exception:
            continue
    return None, 0


async def run_doctor(query: str = "coffee in Austin TX", headless: bool = False) -> bool:
    """Check every selector against a live search. Returns True if usable."""
    console.print(f"[cyan]Running preflight against[/cyan] [bold]{query}[/bold]...")

    cfg = RunConfig(target_input=query, headless=headless)
    browser = BrowserManager(headless=headless, proxy=cfg.proxy_dict())
    results: dict[str, tuple[str | None, int]] = {}
    notes: list[str] = []

    try:
        page = await browser.start()
        unit = SearchUnit(category="coffee", query=query, city=query)

        await page.goto(unit.url, wait_until="domcontentloaded", timeout=settings.NAV_TIMEOUT_MS)

        if await is_blocked(page):
            console.print(
                "[bold red]BLOCKED[/bold red] — Google served a CAPTCHA or block page. "
                "Selectors could not be checked. Try again later or use a proxy."
            )
            return False

        for sel in SELECTORS["results_feed"]:
            try:
                await page.locator(sel).first.wait_for(
                    state="visible", timeout=settings.RESULTS_FEED_TIMEOUT_MS
                )
                break
            except Exception:
                continue

        await scroll_results(page, max_results=20)

        for key in _LIST_KEYS:
            results[key] = await _first_matching(page, key)

        # Open a result so the detail-panel selectors can be checked too.
        # Scope to the feed: the first matching link on the page is often a
        # sponsored placement, whose panel is not a normal business listing.
        link_selector = await find_result_selector(page)
        feed_selector = await find_feed_selector(page)
        opened = False

        if link_selector:
            # Same collection path the scraper uses, so sponsored placements
            # are filtered out here too.
            hrefs = await collect_result_hrefs(page, link_selector, feed_selector)

            # Any single card can fail to open; try a few before concluding
            # the selectors are broken.
            for href in hrefs[:3]:
                locator = page.locator(f'a[href="{css_attr_escape(href)}"]').first
                if await locator.count() == 0:
                    continue
                if not await human_click(page, locator):
                    continue
                await detail_delay()
                if await wait_for_detail_panel(page):
                    opened = True
                    break
                await page.keyboard.press("Escape")
                await detail_delay()

        if opened:
            for key in _DETAIL_KEYS:
                results[key] = await _first_matching(page, key)

            raw = await extract_detail(page)
            filled = [k for k, v in raw.items() if v not in (None, "", [])]
            notes.append(f"Detail extraction returned {len(filled)} populated fields.")
            if raw.get("name"):
                notes.append(f"Sample business: {raw['name']}")
        else:
            notes.append("Could not open a detail panel — detail selectors unchecked.")

    except Exception as exc:
        console.print(f"[red]Preflight failed:[/red] {exc}")
        return False
    finally:
        await browser.close()

    # --- Report ---
    table = Table(title="Selector health", header_style="bold cyan")
    table.add_column("Selector key")
    table.add_column("Status", justify="center")
    table.add_column("Matched", justify="right")
    table.add_column("Winning selector", overflow="fold")

    critical_failed = False
    for key in _LIST_KEYS + _DETAIL_KEYS:
        if key not in results:
            table.add_row(key, "[dim]skipped[/dim]", "-", "-")
            continue
        selector, count = results[key]
        is_critical = key in CRITICAL_SELECTOR_KEYS
        if selector:
            status = "[green]PASS[/green]"
        elif is_critical:
            status = "[bold red]FAIL[/bold red]"
            critical_failed = True
        else:
            # Plenty of businesses genuinely have no email, website or price.
            status = "[yellow]none[/yellow]"
        # Selectors are full of square brackets, which Rich would otherwise
        # parse as markup tags and swallow.
        table.add_row(key, status, str(count), escape(selector) if selector else "-")

    console.print(table)
    for note in notes:
        console.print(f"[dim]{note}[/dim]")

    if critical_failed:
        console.print(
            "\n[bold red]Critical selectors failed.[/bold red] Google's markup has "
            "likely changed — update [bold]scraper/selectors.py[/bold]. Scraping now "
            "would silently return nothing."
        )
        return False

    console.print("\n[bold green]Preflight passed.[/bold green] Core selectors are working.")
    return True
