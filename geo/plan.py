"""Expand a Target + categories + depth into a flat list of SearchUnits."""

import logging

from config.enums import Depth
from geo.areas import area_query
from geo.grid import build_grid, suggested_zoom
from geo.models import SearchUnit, Target

logger = logging.getLogger(__name__)


def build_query(category: str, place: str) -> str:
    """The search text Google Maps gets."""
    place = place.strip()
    return f"{category} in {place}" if place else category


def plan_city(target: Target, categories: list[str]) -> list[SearchUnit]:
    """One search per category, scoped to the whole city."""
    return [
        SearchUnit(
            category=category,
            query=build_query(category, target.query),
            city=target.query,
            region=target.region,
        )
        for category in categories
    ]


def plan_areas(target: Target, categories: list[str], areas: list[str]) -> list[SearchUnit]:
    """One search per (sub-area x category).

    Falls back to city depth when area discovery found nothing, so a run never
    silently produces zero units.
    """
    if not areas:
        logger.warning("No sub-areas discovered; falling back to city-wide search.")
        return plan_city(target, categories)

    units: list[SearchUnit] = []
    for area in areas:
        place = area_query(area, target.query)
        for category in categories:
            units.append(SearchUnit(
                category=category,
                query=build_query(category, place),
                city=target.query,
                area=area,
                region=target.region,
            ))
    return units


def plan_grid(
    target: Target,
    categories: list[str],
    rows: int = 3,
    cols: int = 3,
    span_km: float = 18.0,
    zoom: float | None = None,
) -> list[SearchUnit]:
    """One search per (map tile x category)."""
    if not target.has_coords:
        logger.warning(
            "Target has no coordinates; grid depth is unavailable, using city-wide search."
        )
        return plan_city(target, categories)

    tiles = build_grid(target.lat, target.lng, span_km=span_km, rows=rows, cols=cols)
    tile_zoom = zoom if zoom is not None else suggested_zoom(span_km, rows, cols)

    units: list[SearchUnit] = []
    for tile in tiles:
        for category in categories:
            units.append(SearchUnit(
                category=category,
                # The query stays city-scoped; the @lat,lng,zoom fragment is
                # what actually pins the search to the tile.
                query=build_query(category, target.query),
                city=target.query,
                region=target.region,
                lat=tile["lat"],
                lng=tile["lng"],
                zoom=tile_zoom,
                tile=tile["tile"],
            ))
    return units


def build_search_plan(
    target: Target,
    categories: list[str],
    depth: Depth,
    areas: list[str] | None = None,
    grid_rows: int = 3,
    grid_cols: int = 3,
    grid_span_km: float = 18.0,
    grid_zoom: float | None = None,
) -> list[SearchUnit]:
    """Build the full run plan for a target."""
    if not categories:
        return []

    if depth is Depth.AREAS:
        return plan_areas(target, categories, areas or [])
    if depth is Depth.GRID:
        return plan_grid(target, categories, grid_rows, grid_cols, grid_span_km, grid_zoom)
    return plan_city(target, categories)
