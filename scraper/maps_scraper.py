"""Core Google Maps scraping engine."""

import asyncio
import logging
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin

from playwright.async_api import Page

from config import settings
from config.runconfig import RunConfig
from data.models import Business
from geo.models import SearchUnit
from geo.parsing import parse_place_href
from scraper.anti_detect import detail_delay, human_click, is_blocked, maybe_idle_pause
from scraper.extract import extract_detail, extract_website_contacts
from scraper.parsers import (
    clean_hours,
    clean_price_level,
    collect_socials,
    contact_page_urls,
    email_from_mailto,
    find_emails,
    is_valid_email,
    normalize_website,
    parse_rating,
    parse_review_count,
)
from scraper.retry import retry_async
from scraper.scroll import find_feed, find_result_selector, scroll_results
from scraper.selectors import SELECTORS

logger = logging.getLogger(__name__)

MAPS_ORIGIN = "https://www.google.com"

# Wall-clock ceiling for a single result: open panel + extract + optional
# website excursion. Generous enough never to fire on a healthy result.
RESULT_BUDGET_SECONDS = 150.0

# How long to wait for the detail panel to actually swap to the clicked
# business before falling back to direct navigation.
PANEL_SWAP_TIMEOUT_S = 8.0


@dataclass
class UnitResult:
    """Outcome of scraping one SearchUnit."""

    businesses: list[Business] = field(default_factory=list)
    processed: set[str] = field(default_factory=set)
    total_cards: int = 0
    blocked: bool = False
    error: str | None = None

    @property
    def found(self) -> int:
        return len(self.businesses)


# Google interleaves paid placements into the results feed. They carry a
# "Sponsored" label on the card (or on the link itself) and are excluded here.
_COLLECT_HREFS_JS = r"""
els => {
  const isSponsored = (el) => {
    const label = el.getAttribute('aria-label') || '';
    if (/\bsponsored\b/i.test(label)) return true;
    const card = el.closest('div[role="article"]')
              || el.closest('div[jsaction]')
              || el.parentElement;
    if (!card) return false;
    return /\bsponsored\b/i.test(card.innerText || '');
  };
  return els
    .filter(e => !isSponsored(e))
    .map(e => e.getAttribute('href'))
    .filter(Boolean);
}
"""


def css_attr_escape(value: str) -> str:
    """Escape a value for use inside a CSS [attr="..."] selector."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def wait_for_detail_panel(page: Page) -> bool:
    """Wait for the business detail panel to load.

    The selector chain deliberately excludes a bare ``h1`` — that matched
    almost any page state and let half-loaded panels report as ready.
    """
    for sel in SELECTORS["detail_loaded"]:
        try:
            await page.locator(sel).first.wait_for(
                state="visible", timeout=settings.DETAIL_LOAD_TIMEOUT_MS
            )
            return True
        except Exception:
            continue
    return False


async def collect_result_hrefs(
    page: Page, selector: str, feed_selector: str | None = None
) -> list[str]:
    """Snapshot every result link's href, in feed order, de-duplicated.

    Hrefs are stable identities. Iterating by ``.nth(i)`` re-resolves by
    position while the virtualized feed reflows after every panel close, which
    silently skipped and revisited cards.

    Sponsored placements are dropped: they are interleaved into the feed and
    look like ordinary results, but an ad is not a lead.
    """
    async def _query(sel: str) -> list[str]:
        return await page.eval_on_selector_all(sel, _COLLECT_HREFS_JS)

    raw: list[str] = []
    try:
        if feed_selector:
            raw = await _query(f"{feed_selector} {selector}")
        if not raw:
            # No feed, or the scope matched nothing — fall back to the whole page
            # rather than returning zero results.
            raw = await _query(selector)
    except Exception as exc:
        logger.warning(f"Could not collect result hrefs: {exc}")
        return []

    seen: set[str] = set()
    hrefs: list[str] = []
    for href in raw:
        if href in seen:
            continue
        seen.add(href)
        hrefs.append(href)
    return hrefs


async def _scrape_website_inner(page: Page, website_url: str) -> tuple[str | None, dict]:
    email: str | None = None
    socials: dict[str, str] = {}
    new_page = None

    try:
        new_page = await page.context.new_page()
        # Business sites are arbitrary third-party pages: cap every operation,
        # not just navigation, so a page that never settles cannot wedge us.
        new_page.set_default_timeout(settings.WEBSITE_TIMEOUT_MS)
        new_page.set_default_navigation_timeout(settings.WEBSITE_TIMEOUT_MS)
        targets = [website_url] + contact_page_urls(website_url, limit=2)

        for index, url in enumerate(targets):
            try:
                await new_page.goto(
                    url, wait_until="domcontentloaded", timeout=settings.WEBSITE_TIMEOUT_MS
                )
            except Exception as exc:
                logger.debug(f"Website fetch failed for {url}: {exc}")
                continue

            data = await extract_website_contacts(new_page)

            if not email:
                for href in data.get("emails", []):
                    candidate = email_from_mailto(href)
                    if candidate:
                        email = candidate
                        break
            if not email:
                candidates = find_emails(data.get("text", ""))
                if candidates:
                    email = candidates[0]

            for network, url_found in collect_socials(data.get("links", [])).items():
                socials.setdefault(network, url_found)

            if email and socials:
                break
            # Only pay for contact-page hops when the homepage came up empty.
            if email and index == 0:
                break
    finally:
        if new_page:
            try:
                await new_page.close()
            except Exception:
                pass

    return email, socials


async def _scrape_website(page: Page, website_url: str, cfg: RunConfig) -> tuple[str | None, dict]:
    """Visit a business website hunting for an email and social profiles.

    Falls back to /contact and /about when the homepage yields nothing —
    that's where small-business email addresses usually live.

    The whole excursion runs under a hard wall-clock budget. Per-operation
    timeouts are not enough: a page that navigates continuously can keep
    ``evaluate`` waiting for an execution context indefinitely, and one
    hostile business site must never stall the entire run.
    """
    budget = (settings.WEBSITE_TIMEOUT_MS / 1000.0) * 3 + 10.0
    try:
        return await asyncio.wait_for(
            _scrape_website_inner(page, website_url), timeout=budget
        )
    except asyncio.TimeoutError:
        logger.debug(f"Website scrape timed out after {budget:.0f}s: {website_url}")
    except Exception as exc:
        logger.debug(f"Website scrape failed for {website_url}: {exc}")
    return None, {}


def _build_business(raw: dict, href: str, unit: SearchUnit) -> Business | None:
    """Turn a raw detail-panel dict plus its result href into a Business."""
    name = (raw.get("name") or "").strip()
    if not name:
        return None

    # The detail-panel chain falls back to the results pane when no business
    # panel is open. That pane has no aria-label and none of the contact rows,
    # so it would otherwise be recorded as a business called "Results".
    if not raw.get("panelLabel") and not any(
        raw.get(field) for field in ("address", "phone", "websiteUrl", "plusCode")
    ):
        logger.debug(f"Discarding non-business panel: {name!r}")
        return None

    place_id, lat, lng = parse_place_href(href)
    website_url = normalize_website(raw.get("websiteUrl"))
    email = raw.get("email")
    email = email.strip() if isinstance(email, str) else None
    if email and not is_valid_email(email):
        email = None

    return Business(
        name=name,
        place_id=place_id,
        category=(raw.get("category") or None),
        address=(raw.get("address") or None),
        phone=(raw.get("phone") or None),
        email=email,
        has_website=bool(website_url),
        website_url=website_url,
        rating=parse_rating(raw.get("ratingText")),
        review_count=parse_review_count(raw.get("reviewsText")),
        claimed=raw.get("claimed"),
        latitude=lat,
        longitude=lng,
        plus_code=(raw.get("plusCode") or None),
        hours=clean_hours(raw.get("hours")),
        price_level=clean_price_level(raw.get("priceLevel")),
        google_maps_url=urljoin(MAPS_ORIGIN, href),
        city=unit.city,
        area=unit.area,
        metro_area=unit.city,
        state=unit.region,
        search_query=unit.query,
    )


def _href_name(href: str) -> str | None:
    """The business name Google put in the result URL path."""
    match = re.search(r"/maps/place/([^/@?]+)", href or "")
    if not match:
        return None
    return unquote(match.group(1)).replace("+", " ").strip() or None


def _href_signature(href: str) -> str | None:
    """A token that must appear in the page URL once the right panel is open.

    Prefers the place id; falls back to the name slug in the URL path.
    """
    place_id, _lat, _lng = parse_place_href(href)
    if place_id:
        return place_id
    match = re.search(r"/maps/place/([^/@?]+)", href or "")
    return match.group(1) if match else None


def _match_key(text: str | None) -> str:
    """Reduce a name to letters and digits for tolerant comparison."""
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def names_match(expected: str | None, actual: str | None) -> bool:
    """Whether a panel's label plausibly refers to the expected business.

    Google's URL slug often carries extra marketing text ("Lost Edge Tattoo |
    Best Tattoo Shop in Austin, TX") while the panel shows the plain name, so
    containment either way counts — but only for strings long enough that
    containment means something.
    """
    want, got = _match_key(expected), _match_key(actual)
    if not want or not got:
        return False
    if want == got:
        return True
    if min(len(want), len(got)) < 5:
        return False
    return want in got or got in want


_PANEL_LABEL_JS = """
() => {
  const p = document.querySelector('div[role="main"][aria-label]');
  return p ? p.getAttribute('aria-label') : null;
}
"""


async def _wait_for_panel_named(page: Page, expected_name: str, timeout_s: float) -> bool:
    """Poll until the open detail panel is labelled with the expected business.

    The URL alone is not enough: Google pushes the new URL before the panel's
    DOM swaps, so a check on the URL can still catch the *previous* business's
    panel and attribute its phone and address to the wrong listing.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    while loop.time() < deadline:
        try:
            label = await page.evaluate(_PANEL_LABEL_JS)
        except Exception:
            label = None
        if names_match(expected_name, label):
            return True
        await asyncio.sleep(0.2)
    return False


async def _wait_for_url_match(page: Page, signature: str, timeout_s: float) -> bool:
    """Poll until the page URL refers to the place we clicked.

    Without this the scraper can read a *stale* panel: the detail-panel
    selector matches the previously opened business immediately, so the fields
    get attributed to the wrong listing. Google updates the URL when the panel
    actually swaps, which makes it the reliable signal.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s
    needle = unquote(signature).lower()
    while loop.time() < deadline:
        try:
            if needle in unquote(page.url).lower():
                return True
        except Exception:
            pass
        await asyncio.sleep(0.2)
    return False


async def _open_result(page: Page, href: str, direct: bool) -> tuple[bool, bool]:
    """Open a result's detail panel.

    Returns ``(opened, went_direct)``. Clicking the card is cheaper than a full
    navigation, so it is the fast path; when the card is no longer in the
    virtualized feed we navigate straight to its URL instead.
    """
    signature = _href_signature(href)
    expected_name = _href_name(href)

    if not direct:
        selector = f'a[href="{css_attr_escape(href)}"]'
        try:
            locator = page.locator(selector).first
            if await locator.count() > 0 and await human_click(page, locator):
                await detail_delay()

                # Confirm the panel really is for *this* business before
                # trusting a single field off it. Both gates matter: the URL
                # changes first, the panel DOM swaps a moment later.
                matched = True
                if signature:
                    matched = await _wait_for_url_match(
                        page, signature, PANEL_SWAP_TIMEOUT_S
                    )
                if matched and expected_name:
                    matched = await _wait_for_panel_named(
                        page, expected_name, PANEL_SWAP_TIMEOUT_S
                    )

                if matched and await wait_for_detail_panel(page):
                    return True, False

                logger.debug(
                    f"Panel did not swap to {expected_name!r}; navigating directly."
                )
        except Exception as exc:
            logger.debug(f"Click path failed for {href}: {exc}")

    # Direct navigation: reliable, and once we hold every href we no longer
    # need the feed at all.
    try:
        await retry_async(
            lambda: page.goto(
                urljoin(MAPS_ORIGIN, href),
                wait_until="domcontentloaded",
                timeout=settings.NAV_TIMEOUT_MS,
            ),
            description=f"open {href[:60]}",
            attempts=2,
        )
        await detail_delay()
        return await wait_for_detail_panel(page), True
    except Exception as exc:
        logger.debug(f"Direct navigation failed for {href}: {exc}")
        return False, True


async def _return_to_feed(page: Page) -> bool:
    """Close the detail panel and confirm the results feed is back."""
    try:
        await page.keyboard.press("Escape")
    except Exception:
        return False
    await detail_delay()
    return await find_feed(page, timeout_ms=5000) is not None


async def search_and_scrape(
    page: Page,
    unit: SearchUnit,
    cfg: RunConfig,
    *,
    on_business=None,
    on_progress=None,
    on_processed=None,
    skip_hrefs: set[str] | None = None,
) -> UnitResult:
    """Execute one Google Maps search and extract every result's details.

    Args:
        page: Playwright page with stealth applied.
        unit: The search to run (carries the query and any lat/lng pin).
        cfg: Run configuration (result caps, website crawling, ...).
        on_business: Called immediately after each business is extracted, for
            incremental export. Signature ``on_business(business)``.
        on_progress: Called as ``on_progress(done, total)`` for the UI.
        on_processed: Called as ``on_processed(href)`` once a result has been
            handled, so the caller can checkpoint resume state as it goes.
        skip_hrefs: Result links already processed on a previous run — used to
            resume a unit mid-way instead of redoing every detail visit.

    Returns:
        A ``UnitResult`` with the businesses found and the hrefs processed.
    """
    result = UnitResult()
    skip_hrefs = skip_hrefs or set()

    logger.info(f"Searching: {unit.query} -> {unit.url}")

    try:
        await retry_async(
            lambda: page.goto(
                unit.url, wait_until="domcontentloaded", timeout=settings.NAV_TIMEOUT_MS
            ),
            description=f"search '{unit.query}'",
        )
    except Exception as exc:
        result.error = f"navigation failed: {exc}"
        return result

    if await is_blocked(page):
        result.blocked = True
        result.error = "blocked before results loaded"
        return result

    # Wait for the results feed. A pinned single result skips the feed
    # entirely and lands straight on a place page.
    feed_selector: str | None = None
    for sel in SELECTORS["results_feed"]:
        try:
            await page.locator(sel).first.wait_for(
                state="visible", timeout=settings.RESULTS_FEED_TIMEOUT_MS
            )
            feed_selector = sel
            break
        except Exception:
            continue

    if not feed_selector:
        if await wait_for_detail_panel(page):
            raw = await extract_detail(page)
            business = _build_business(raw, page.url, unit)
            if business:
                result.businesses.append(business)
                result.total_cards = 1
                if on_business:
                    on_business(business)
            return result
        result.error = "no results feed"
        return result

    await scroll_results(page, max_results=cfg.max_results_per_unit)

    selector = await find_result_selector(page)
    if not selector:
        # Every result-link selector missed. That is a markup change, not a
        # block — say so, because the two need completely different fixes.
        result.error = (
            "no result links matched any selector — Google markup may have changed; "
            "run `python main.py --doctor`"
        )
        return result

    hrefs = await collect_result_hrefs(page, selector, feed_selector)
    if cfg.max_results_per_unit:
        hrefs = hrefs[: cfg.max_results_per_unit]

    result.total_cards = len(hrefs)
    pending = [h for h in hrefs if h not in skip_hrefs]
    logger.info(
        f"Found {len(hrefs)} result cards"
        + (f" ({len(hrefs) - len(pending)} already done)" if len(pending) != len(hrefs) else "")
    )

    direct_mode = False
    since_block_check = 0

    async def _scrape_one(href: str) -> tuple[Business | None, bool]:
        """Open one result and extract it. Returns (business, went_direct)."""
        opened, went_direct = await _open_result(page, href, direct_mode)
        if not opened:
            return None, went_direct

        raw = await extract_detail(page)
        business = _build_business(raw, href, unit)

        # Final integrity gate. If the extracted name still does not match the
        # business this href points at, we are looking at a stale panel and
        # would otherwise file another company's phone and address under this
        # listing. Re-fetch the place directly, which cannot be stale.
        expected_name = _href_name(href)
        if business and expected_name and not names_match(expected_name, business.name):
            logger.debug(
                f"Name mismatch (href={expected_name!r}, panel={business.name!r}); "
                "re-fetching directly."
            )
            opened, went_direct = await _open_result(page, href, direct=True)
            if not opened:
                return None, True
            raw = await extract_detail(page)
            business = _build_business(raw, href, unit)
            if business and not names_match(expected_name, business.name):
                logger.warning(
                    f"Discarding result: expected {expected_name!r}, "
                    f"panel reported {business.name!r}."
                )
                return None, True

        if business and cfg.crawl_websites and business.has_website and not business.email:
            email, socials = await _scrape_website(page, business.website_url, cfg)
            if email:
                business.email = email
            business.facebook = socials.get("facebook")
            business.instagram = socials.get("instagram")
            business.linkedin = socials.get("linkedin")

        return business, went_direct

    for index, href in enumerate(pending, start=1):
        try:
            # Hard per-result budget. Every individual call already has its own
            # timeout, but this guarantees the loop keeps moving no matter what
            # a page does — one bad result costs one result, never the unit.
            business, went_direct = await asyncio.wait_for(
                _scrape_one(href), timeout=RESULT_BUDGET_SECONDS
            )
            if went_direct:
                # The feed is gone now; stay in direct mode for the rest.
                direct_mode = True

            if business is None:
                logger.debug(f"[{index}/{len(pending)}] No business extracted.")
                result.processed.add(href)
                if on_processed:
                    on_processed(href)
                if on_progress:
                    on_progress(index, len(pending))
                continue

            result.processed.add(href)
            if on_processed:
                on_processed(href)

            result.businesses.append(business)
            logger.debug(
                f"  [{index}/{len(pending)}] {business.name} | "
                f"website={business.has_website} | email={business.email}"
            )
            if on_business:
                on_business(business)

            if on_progress:
                on_progress(index, len(pending))

            if not direct_mode:
                await _return_to_feed(page)

        except asyncio.TimeoutError:
            logger.warning(
                f"  [{index}/{len(pending)}] Timed out after "
                f"{RESULT_BUDGET_SECONDS}s; skipping."
            )
            result.processed.add(href)
            if on_processed:
                on_processed(href)
            # A stuck page may still be mid-navigation; go back to a known state.
            direct_mode = True
            continue
        except Exception as exc:
            logger.error(f"  [{index}/{len(pending)}] Failed to extract: {exc}")
            result.processed.add(href)
            if on_processed:
                on_processed(href)
            continue

        # Mid-search block detection. Checking only before a search meant a
        # CAPTCHA appearing partway through produced a whole search of blanks
        # before anything noticed.
        since_block_check += 1
        if since_block_check >= settings.BLOCK_CHECK_EVERY:
            since_block_check = 0
            if await is_blocked(page, timeout_ms=800):
                result.blocked = True
                result.error = "blocked mid-search"
                logger.warning("Block detected mid-search; stopping this unit.")
                break

        await maybe_idle_pause()

    logger.info(f"Extracted {result.found} businesses from '{unit.query}'")
    return result

