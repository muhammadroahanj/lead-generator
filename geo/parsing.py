"""Pure parsers for Google Maps URLs. Unit-tested offline."""

import re

# ".../@29.7604267,-95.3698028,13z/..." — how the *search* URL carries the map
# centre.
_AT_COORDS_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,(\d+(?:\.\d+)?)z)?")

# "!8m2!3d30.3578911!4d-97.7482485" — how a *result href* carries the place's
# own coordinates. Result links have no "@" fragment at all, so this is the
# only way to get per-business lat/lng for free.
_DATA_COORDS_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")

# Google's internal place identity, e.g. "!1s0x8640b8b4488d8501:0xca0d02def365053b"
_PLACE_HEX_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", re.IGNORECASE)
_PLACE_CID_RE = re.compile(r"!1s([A-Za-z0-9_-]{20,})")
_PLACE_ID_PARAM_RE = re.compile(r"[?&]place_id=([A-Za-z0-9_-]+)")


def parse_at_coords(url: str | None) -> tuple[float | None, float | None, float | None]:
    """Extract (lat, lng, zoom) from an ``@lat,lng,zoomz`` fragment."""
    if not url:
        return None, None, None
    match = _AT_COORDS_RE.search(url)
    if not match:
        return None, None, None
    lat = float(match.group(1))
    lng = float(match.group(2))
    zoom = float(match.group(3)) if match.group(3) else None
    if not _valid_coords(lat, lng):
        return None, None, None
    return lat, lng, zoom


def parse_place_id(url: str | None) -> str | None:
    """Extract a stable place identifier from a Maps place URL.

    Google exposes several forms; any of them is a far better dedup key than
    a normalized name, and all of them are already in the href we clicked.
    """
    if not url:
        return None
    for pattern in (_PLACE_ID_PARAM_RE, _PLACE_HEX_RE, _PLACE_CID_RE):
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def _valid_coords(lat: float, lng: float) -> bool:
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0


def parse_data_coords(url: str | None) -> tuple[float | None, float | None]:
    """Extract (lat, lng) from the ``!3d<lat>!4d<lng>`` part of a place URL."""
    if not url:
        return None, None
    match = _DATA_COORDS_RE.search(url)
    if not match:
        return None, None
    lat, lng = float(match.group(1)), float(match.group(2))
    return (lat, lng) if _valid_coords(lat, lng) else (None, None)


def parse_place_href(href: str | None) -> tuple[str | None, float | None, float | None]:
    """Return (place_id, lat, lng) for a result link.

    Result hrefs put the business's own coordinates in the ``data=`` blob, so
    that is tried first; the ``@`` fragment (the map centre) is only a
    fallback, and is absent from result links entirely.
    """
    lat, lng = parse_data_coords(href)
    if lat is None:
        lat, lng, _ = parse_at_coords(href)
    return parse_place_id(href), lat, lng
