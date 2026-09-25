"""Resolve a free-form place against Google Maps, and subdivide it.

Both jobs are done with Maps itself — no geocoding service, no API key, so
this works for any city in any country:

  * ``resolve_target`` reads the ``@lat,lng,zoom`` fragment Google puts in the
    URL after a search. That is the city centre, for free.
  * ``discover_subareas`` runs one capped probe search and ranks the localities
    appearing in the resulting addresses. Those become the sub-area queries.
"""

import asyncio
import logging

from playwright.async_api import Page

from config import settings
from config.runconfig import RunConfig
from data.normalize import address_parts, collapse
from geo.areas import rank_subareas
from geo.models import SearchUnit, Target
from geo.parsing import parse_at_coords
from geo.plan import build_query
from scraper.retry import retry_async
from scraper.selectors import SELECTORS

logger = logging.getLogger(__name__)

MAPS_SEARCH = "https://www.google.com/maps/search"

# Trailing components that are a country rather than a region.
_COUNTRY_HINTS = {
    "usa", "united states", "uk", "united kingdom", "canada", "australia",
    "pakistan", "india", "ireland", "new zealand", "south africa",
}


async def _read_search_box(page: Page) -> str | None:
    """Read back what Maps resolved the query to."""
    for sel in SELECTORS["search_box"]:
        try:
            value = await page.locator(sel).first.input_value(timeout=2000)
            if value and value.strip():
                return value.strip()
        except Exception:
            continue
    return None


async def _wait_for_coords(page: Page, timeout_s: float = 15.0):
    """Poll the page URL until Google appends its @lat,lng,zoom fragment."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        lat, lng, zoom = parse_at_coords(page.url)
        if lat is not None:
            return lat, lng, zoom
        await asyncio.sleep(0.5)
    return None, None, None


async def resolve_target(page: Page, raw_input: str) -> Target:
    """Resolve a user-typed place into a Target with coordinates.

    Never raises: a target without coordinates still works for city and area
    depth, it only rules out grid depth.
    """
    raw_input = raw_input.strip()
    from urllib.parse import quote_plus

    url = f"{MAPS_SEARCH}/{quote_plus(raw_input)}"

    try:
        await retry_async(
            lambda: page.goto(
                url, wait_until="domcontentloaded", timeout=settings.NAV_TIMEOUT_MS
            ),
            description=f"resolve '{raw_input}'",
            attempts=2,
        )
    except Exception as exc:
        logger.warning(f"Could not resolve '{raw_input}': {exc}")
        return Target(raw=raw_input, display_name=raw_input)

    lat, lng, zoom = await _wait_for_coords(page)
    display = await _read_search_box(page) or raw_input

    target = Target(
        raw=raw_input,
        display_name=display,
        lat=lat,
        lng=lng,
        zoom=zoom,
        region=_region_from_input(display),
    )
    if target.has_coords:
        logger.info(
            f"Resolved '{raw_input}' -> {target.query} @ {target.lat:.4f},{target.lng:.4f}"
        )
    else:
        logger.warning(
            f"Resolved '{raw_input}' but found no coordinates; grid depth unavailable."
        )
    return target


def _region_from_input(text: str) -> str | None:
    """Best-effort state/province from a 'City, ST' or 'City ST' string."""
    parts = address_parts(text)
    if len(parts) >= 2:
        tail = parts[-1].strip()
        if collapse(tail) in _COUNTRY_HINTS and len(parts) >= 3:
            tail = parts[-2].strip()
        if 2 <= len(tail) <= 20 and collapse(tail) not in _COUNTRY_HINTS:
            return tail
    # "Houston TX" — a trailing 2-letter uppercase token.
    tokens = text.split()
    if len(tokens) >= 2 and len(tokens[-1]) == 2 and tokens[-1].isupper():
        return tokens[-1]
    return None


async def discover_subareas(
    page: Page,
    target: Target,
    cfg: RunConfig,
    probe_category: str,
    on_business=None,
    probe_limit: int = 40,
) -> tuple[list[str], list]:
    """Discover a city's sub-areas from the addresses Maps returns.

    Runs one capped city-wide search, then ranks the localities and postal
    codes appearing in those addresses. The probe's businesses are returned so
    the caller can export them — the work is not thrown away.

    Returns:
        ``(areas, businesses)``.
    """
    from scraper.maps_scraper import search_and_scrape

    probe_unit = SearchUnit(
        category=probe_category,
        query=build_query(probe_category, target.query),
        city=target.query,
        region=target.region,
    )

    probe_cfg = RunConfig(
        target_input=cfg.target_input,
        profile=cfg.profile,
        min_rating=cfg.min_rating,
        min_reviews=cfg.min_reviews,
        require_phone=cfg.require_phone,
        headless=cfg.headless,
        proxy=cfg.proxy,
        # Keep the probe cheap: no website crawling, hard result cap.
        fetch_website_email=False,
        max_results_per_unit=probe_limit,
        output=cfg.output,
    )

    logger.info(f"Probing '{probe_unit.query}' to discover sub-areas...")
    result = await search_and_scrape(page, probe_unit, probe_cfg, on_business=on_business)

    addresses = [b.address for b in result.businesses if b.address]
    if not addresses:
        logger.warning("Area probe found no addresses; sub-area discovery unavailable.")
        return [], result.businesses

    areas = rank_subareas(
        addresses,
        city=target.query,
        region=target.region or "",
        max_areas=cfg.max_subareas,
    )
    logger.info(
        f"Discovered {len(areas)} sub-areas from {len(addresses)} addresses: "
        + ", ".join(areas[:8]) + ("..." if len(areas) > 8 else "")
    )
    return areas, result.businesses
