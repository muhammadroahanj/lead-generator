"""Geography value objects: a resolved Target and the SearchUnits it expands to."""

from dataclasses import dataclass
from urllib.parse import quote_plus

MAPS_SEARCH_BASE = "https://www.google.com/maps/search"


@dataclass(frozen=True)
class Target:
    """A place the user asked for, resolved against Google Maps.

    ``lat``/``lng``/``zoom`` come from the ``@lat,lng,zoom`` fragment Google
    puts in the URL after a search — free geocoding with no API key.
    """

    raw: str                       # exactly what the user typed
    display_name: str = ""         # what Maps' search box resolved it to
    lat: float | None = None
    lng: float | None = None
    zoom: float | None = None
    region: str | None = None      # state / province, when detectable
    country: str | None = None

    @property
    def query(self) -> str:
        """The string to embed in search queries."""
        return (self.display_name or self.raw).strip()

    @property
    def has_coords(self) -> bool:
        return self.lat is not None and self.lng is not None


@dataclass(frozen=True)
class SearchUnit:
    """One Google Maps search: a category, scoped to a place or a map tile.

    The whole run is a flat list of these, so the orchestrator never needs to
    know which depth produced them.
    """

    category: str
    query: str                     # full search text, e.g. "plumbers in Katy TX"
    city: str = ""
    area: str | None = None        # sub-area name, when depth=AREAS
    region: str | None = None
    lat: float | None = None       # tile centre, when depth=GRID
    lng: float | None = None
    zoom: float | None = None
    tile: str | None = None        # e.g. "r2c3", when depth=GRID

    @property
    def key(self) -> str:
        """Stable identity for progress/checkpoint files."""
        scope = self.tile or self.area or self.city or self.query
        return f"{scope}::{self.category}"

    @property
    def label(self) -> str:
        """Short human-readable description for the dashboard."""
        if self.tile:
            return f"{self.category} @ {self.city} [{self.tile}]"
        if self.area:
            return f"{self.category} in {self.area}"
        return f"{self.category} in {self.city or self.query}"

    @property
    def url(self) -> str:
        """The Google Maps URL for this search.

        Pinning a tile with ``@lat,lng,zoom`` makes Google's ~120-result cap
        apply per tile instead of per city, which is the entire point of grid
        depth.
        """
        base = f"{MAPS_SEARCH_BASE}/{quote_plus(self.query)}"
        if self.lat is not None and self.lng is not None:
            zoom = self.zoom if self.zoom is not None else 14
            return f"{base}/@{self.lat:.7f},{self.lng:.7f},{zoom:g}z"
        return base
