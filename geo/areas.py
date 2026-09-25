"""Derive a city's sub-areas from the addresses Google Maps already gave us.

No geocoding service, no API key, works in any country: run one probe search,
read the addresses off the results, and the localities and postal codes fall
straight out of them. Ranking by frequency keeps the areas that actually have
businesses in them, which is exactly what we want to search next.

``rank_subareas`` is pure and unit-tested; the Playwright side lives in
``geo.resolver``.
"""

import re
from collections import Counter

from data.normalize import address_parts, collapse, extract_postal_code

# Parts that are never a useful sub-area to search.
_GENERIC = {
    "usa", "us", "united states", "uk", "united kingdom", "canada",
    "pakistan", "india", "australia", "unnamed road", "",
}

_HAS_LETTER_RE = re.compile(r"[A-Za-z]")
_STATE_ZIP_RE = re.compile(r"^([A-Za-z .]+?)\s+(\d{5}(?:-\d{4})?)$")


def _split_state_zip(part: str) -> tuple[str | None, str | None]:
    """Split a US-style 'TX 77494' trailing component into (state, zip)."""
    match = _STATE_ZIP_RE.match(part.strip())
    if match:
        return match.group(1).strip(), match.group(2)
    return None, None


def _skip_tokens(city: str, region: str) -> set[str]:
    """Everything that must not be reported as a sub-area.

    ``city`` arrives as whatever Maps resolved it to — often "Austin, TX, USA"
    — so each comma component is excluded individually, not just the whole
    string.
    """
    skip = set(_GENERIC)
    for value in (city, region):
        if not value:
            continue
        skip.add(collapse(value))
        for part in address_parts(value):
            state, _zip = _split_state_zip(part)
            skip.add(collapse(state if state else part))
    skip.discard("")
    return skip


def candidate_areas(address: str, city: str = "", region: str = "") -> list[str]:
    """Sub-area candidates from a single address.

    Drops the street line (first component), the city itself, the region and
    country. What survives is the neighbourhood / suburb / town layer.
    """
    parts = address_parts(address)
    if len(parts) < 2:
        return []

    skip = _skip_tokens(city, region)
    candidates: list[str] = []

    # Skip the first component: it's the street line.
    for part in parts[1:]:
        state, _zip = _split_state_zip(part)
        if state is not None:
            # "TX 77494" is a state+postcode tail, not an area name.
            continue
        cleaned = part.strip()
        if not _HAS_LETTER_RE.search(cleaned):
            continue  # bare numbers / postcodes handled separately
        if collapse(cleaned) in skip:
            continue
        if len(cleaned) < 2:
            continue
        candidates.append(cleaned)

    return candidates


def rank_subareas(
    addresses: list[str],
    city: str = "",
    region: str = "",
    max_areas: int = 12,
    min_count: int = 2,
    include_postcodes: bool = True,
) -> list[str]:
    """Rank sub-areas by how often they appear across the probe addresses.

    Args:
        addresses: Address strings harvested from a probe search.
        city: The city being scraped, so it isn't returned as its own sub-area.
        region: State/province, likewise excluded.
        max_areas: How many sub-areas to return.
        min_count: Ignore areas seen fewer times than this — a single stray
            address is noise, not a neighbourhood. Relaxed automatically when
            it would leave us with nothing.
        include_postcodes: Postal codes make excellent Maps queries (they are
            unambiguous), so they are ranked alongside named areas.

    Returns:
        Area strings ordered most-common first, ready to be combined with the
        city into a search query.
    """
    name_counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    postal_counts: Counter[str] = Counter()

    for address in addresses:
        if not address:
            continue
        for candidate in candidate_areas(address, city, region):
            key = collapse(candidate)
            if not key:
                continue
            name_counts[key] += 1
            display.setdefault(key, candidate)
        if include_postcodes:
            postcode = extract_postal_code(address)
            if postcode:
                postal_counts[postcode] += 1

    def _take(counter: Counter, threshold: int) -> list[tuple[str, int]]:
        return [(k, c) for k, c in counter.most_common() if c >= threshold]

    named = _take(name_counts, min_count)
    postal = _take(postal_counts, min_count) if include_postcodes else []

    # If nothing clears the bar, fall back to single sightings rather than
    # silently degrading the run to city depth.
    if not named and not postal:
        named = _take(name_counts, 1)
        postal = _take(postal_counts, 1) if include_postcodes else []

    merged = [(display[k], c) for k, c in named] + [(k, c) for k, c in postal]
    merged.sort(key=lambda item: (-item[1], item[0]))

    seen: set[str] = set()
    result: list[str] = []
    for name, _count in merged:
        key = collapse(name)
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
        if len(result) >= max_areas:
            break
    return result


def area_query(area: str, city: str) -> str:
    """Combine a discovered area with enough context to be unambiguous.

    Maps resolves a city to something like "Austin, TX, USA", so the region +
    country tail is appended rather than the city name. Discovered areas are
    often *peers* of the city (a suburb like "Katy" near Houston) rather than
    neighbourhoods inside it — "Katy, TX, USA" is right where "Katy, Houston"
    would be wrong. When the city has no tail, the city itself is used.

    Postal codes are already unambiguous and are returned bare; qualifying one
    further only confuses the search.
    """
    area = area.strip()
    city = city.strip()
    if not area:
        return city
    if not city:
        return area
    if not _HAS_LETTER_RE.search(area):
        return area  # postal code

    if collapse(area) in collapse(city):
        return city

    parts = address_parts(city)
    tail = ", ".join(parts[1:]) if len(parts) > 1 else parts[0] if parts else ""
    return f"{area}, {tail}" if tail else area
