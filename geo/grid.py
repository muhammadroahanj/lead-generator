"""Lat/lng tiling for maximum-coverage scraping.

Google returns at most ~120 results per query. Pinning each search to a map
tile with ``@lat,lng,zoom`` makes that cap apply per tile, so an N x M grid
raises the ceiling roughly N*M-fold at the cost of N*M searches.
"""

import math

# Degrees of latitude per kilometre is effectively constant; longitude narrows
# with the cosine of latitude.
_KM_PER_DEG_LAT = 110.574
_KM_PER_DEG_LNG_EQUATOR = 111.320


def km_to_deg_lat(km: float) -> float:
    return km / _KM_PER_DEG_LAT


def km_to_deg_lng(km: float, at_lat: float) -> float:
    """Longitude degrees for a given distance at a given latitude."""
    scale = math.cos(math.radians(max(-89.5, min(89.5, at_lat))))
    # Guard against the poles, where longitude degrees collapse to zero.
    scale = max(scale, 1e-6)
    return km / (_KM_PER_DEG_LNG_EQUATOR * scale)


def build_grid(
    lat: float,
    lng: float,
    span_km: float = 18.0,
    rows: int = 3,
    cols: int = 3,
) -> list[dict]:
    """Tile a square centred on (lat, lng) into ``rows`` x ``cols`` cells.

    Returns one dict per cell with its centre coordinates and an ``r{n}c{n}``
    label used for progress keys.
    """
    rows = max(1, int(rows))
    cols = max(1, int(cols))
    span_km = max(0.1, float(span_km))

    total_lat_deg = km_to_deg_lat(span_km)
    total_lng_deg = km_to_deg_lng(span_km, lat)

    cell_lat = total_lat_deg / rows
    cell_lng = total_lng_deg / cols

    # Centre of the top-left cell.
    start_lat = lat + (total_lat_deg / 2) - (cell_lat / 2)
    start_lng = lng - (total_lng_deg / 2) + (cell_lng / 2)

    tiles = []
    for row in range(rows):
        for col in range(cols):
            tiles.append({
                "lat": round(start_lat - row * cell_lat, 7),
                "lng": round(start_lng + col * cell_lng, 7),
                "tile": f"r{row + 1}c{col + 1}",
                "row": row + 1,
                "col": col + 1,
            })
    return tiles


def suggested_zoom(span_km: float, rows: int, cols: int) -> float:
    """A zoom level that roughly frames one cell.

    Google's zoom is logarithmic: z14 covers a few km, z12 covers tens. Wider
    cells need to zoom out or Maps re-centres the search away from the tile.
    """
    cell_km = span_km / max(1, max(rows, cols))
    if cell_km <= 1.5:
        return 16.0
    if cell_km <= 3.0:
        return 15.0
    if cell_km <= 6.0:
        return 14.0
    if cell_km <= 12.0:
        return 13.0
    return 12.0
