"""Anti-detection utilities: random delays, mouse simulation, block detection."""

import asyncio
import logging
import random

from playwright.async_api import Page

from config.settings import (
    DETAIL_DELAY_MAX,
    DETAIL_DELAY_MIN,
    IDLE_PAUSE_EVERY,
    IDLE_PAUSE_MAX,
    IDLE_PAUSE_MIN,
    SCROLL_DELAY_MAX,
    SCROLL_DELAY_MIN,
    SEARCH_DELAY_MAX,
    SEARCH_DELAY_MIN,
)
from scraper.selectors import SELECTORS

logger = logging.getLogger(__name__)

# Action counter for idle pause scheduling
_action_count = 0
_next_idle_at = random.randint(*IDLE_PAUSE_EVERY)


async def random_delay(min_s: float, max_s: float):
    """Sleep for a random duration between min_s and max_s seconds."""
    await asyncio.sleep(random.uniform(min_s, max_s))


async def scroll_delay():
    await random_delay(SCROLL_DELAY_MIN, SCROLL_DELAY_MAX)


async def detail_delay():
    await random_delay(DETAIL_DELAY_MIN, DETAIL_DELAY_MAX)


async def search_delay():
    await random_delay(SEARCH_DELAY_MIN, SEARCH_DELAY_MAX)


async def maybe_idle_pause():
    """Occasionally pause longer to simulate human reading behavior."""
    global _action_count, _next_idle_at
    _action_count += 1
    if _action_count >= _next_idle_at:
        pause = random.uniform(IDLE_PAUSE_MIN, IDLE_PAUSE_MAX)
        logger.debug(f"Idle pause: {pause:.1f}s (after {_action_count} actions)")
        await asyncio.sleep(pause)
        _action_count = 0
        _next_idle_at = random.randint(*IDLE_PAUSE_EVERY)


async def human_click(page: Page, locator) -> bool:
    """Move the mouse near the element, then click it.

    Escalates through genuinely different strategies. The previous version's
    fallback re-issued the identical ``locator.click()`` that had just failed,
    so it could only ever fail the same way.
    """
    try:
        box = await locator.bounding_box()
        if box:
            target_x = box["x"] + box["width"] / 2 + random.randint(-5, 5)
            target_y = box["y"] + box["height"] / 2 + random.randint(-5, 5)
            await page.mouse.move(target_x, target_y)
            await asyncio.sleep(random.uniform(0.1, 0.3))
        await locator.click(timeout=5000)
        return True
    except Exception as exc:
        logger.debug(f"Normal click failed: {exc}")

    # The element may be scrolled out of the virtualized feed.
    try:
        await locator.scroll_into_view_if_needed(timeout=3000)
        await locator.click(timeout=5000, force=True)
        return True
    except Exception as exc:
        logger.debug(f"Forced click failed: {exc}")

    # Last resort: dispatch the event directly, bypassing hit-testing.
    try:
        await locator.evaluate("el => el.click()")
        return True
    except Exception as exc:
        logger.debug(f"JS click failed: {exc}")

    return False


async def is_blocked(page: Page, timeout_ms: int = 1000) -> bool:
    """Check whether Google has shown a CAPTCHA or block page."""
    for sel in SELECTORS["captcha_indicator"]:
        try:
            if await page.locator(sel).first.is_visible(timeout=timeout_ms):
                logger.warning("CAPTCHA detected!")
                return True
        except Exception:
            pass

    try:
        body_text = await page.inner_text("body", timeout=2000)
        body_lower = body_text.lower()
        for indicator in SELECTORS["block_indicator_text"]:
            if indicator in body_lower:
                logger.warning(f"Block indicator found: '{indicator}'")
                return True
    except Exception:
        pass

    return False


def block_backoff_seconds(consecutive_blocks: int, base: float) -> float:
    """Escalating pause after repeated blocks.

    A flat sleep on the same IP is not a strategy; each additional block
    doubles the wait, capped at an hour.
    """
    multiplier = 2 ** max(0, consecutive_blocks - 1)
    return min(base * multiplier, 3600.0)
