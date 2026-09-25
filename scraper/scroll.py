"""Infinite scroll handler for the Google Maps results feed."""

import logging

from playwright.async_api import Page

from config.settings import MAX_SCROLLS_PER_SEARCH, SCROLL_NO_NEW_RESULTS_LIMIT
from scraper.anti_detect import maybe_idle_pause, scroll_delay
from scraper.selectors import SELECTORS

logger = logging.getLogger(__name__)


async def find_feed(page: Page, timeout_ms: int = 3000):
    """Locate the scrollable results feed element, trying every selector."""
    for sel in SELECTORS["results_feed"]:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=timeout_ms):
                return el
        except Exception:
            continue
    return None


async def find_feed_selector(page: Page, timeout_ms: int = 3000) -> str | None:
    """Return the selector that matched the results feed, not just the element.

    The caller needs the string so it can scope result-link collection to the
    feed — sponsored placements sit outside it and must not be scraped as leads.
    """
    for sel in SELECTORS["results_feed"]:
        try:
            if await page.locator(sel).first.is_visible(timeout=timeout_ms):
                return sel
        except Exception:
            continue
    return None


async def find_result_selector(page: Page) -> str | None:
    """Return the first result-link selector that actually matches something.

    Walking the whole chain matters: hardcoding the first entry meant a single
    Google class rotation produced zero results, which the caller then
    misreported as an IP block on every future run.
    """
    for sel in SELECTORS["result_link"]:
        try:
            if await page.locator(sel).count() > 0:
                return sel
        except Exception:
            continue
    return None


async def _is_end_of_list(page: Page) -> bool:
    for sel in SELECTORS["end_of_list"]:
        try:
            if await page.locator(sel).first.is_visible(timeout=800):
                return True
        except Exception:
            continue
    return False


async def count_result_cards(page: Page) -> int:
    for sel in SELECTORS["result_link"]:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                return count
        except Exception:
            continue
    return 0


async def scroll_results(page: Page, max_results: int | None = None) -> int:
    """Scroll the results feed until it stops yielding new cards.

    Args:
        page: Page showing a Maps search.
        max_results: Stop early once this many cards are loaded.

    Returns:
        Total number of result cards loaded.
    """
    feed = await find_feed(page)
    if not feed:
        logger.warning("Could not find results feed element.")
        return 0

    prev_count = await count_result_cards(page)
    no_new_count = 0

    for scroll_num in range(1, MAX_SCROLLS_PER_SEARCH + 1):
        if max_results and prev_count >= max_results:
            logger.info(f"Reached result cap ({max_results}); stopping scroll.")
            break

        try:
            await feed.evaluate("el => el.scrollTop = el.scrollHeight")
        except Exception as exc:
            # The feed node can be replaced mid-run; re-acquire it once.
            logger.debug(f"Scroll failed ({exc}); re-acquiring feed.")
            feed = await find_feed(page)
            if not feed:
                break
            continue

        await scroll_delay()

        if await _is_end_of_list(page):
            logger.info(f"Reached end of list after {scroll_num} scrolls.")
            break

        current_count = await count_result_cards(page)
        if current_count <= prev_count:
            no_new_count += 1
            if no_new_count >= SCROLL_NO_NEW_RESULTS_LIMIT:
                logger.info(
                    f"No new results after {SCROLL_NO_NEW_RESULTS_LIMIT} scrolls; "
                    f"stopping at {current_count}."
                )
                break
        else:
            no_new_count = 0
            logger.debug(f"Scroll {scroll_num}: {prev_count} -> {current_count} results")

        prev_count = current_count
        await maybe_idle_pause()

    total = await count_result_cards(page)
    logger.info(f"Scroll complete. Total results loaded: {total}")
    return total
