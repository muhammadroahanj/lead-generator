"""Runtime configuration for a single scraper run.

Everything the wizard or CLI can decide lives here and is passed explicitly
down the call chain. Module-level constants in ``config.settings`` are only
defaults — importing one binds it by value, so mutating ``settings.X`` at
runtime would not reach modules that already imported it.
"""

from dataclasses import dataclass, field
from pathlib import Path

from config import settings
from config.enums import Depth, LeadProfile
from config.paths import OutputPaths, default_paths


@dataclass
class RunConfig:
    # --- What to scrape ---
    target_input: str = ""                       # free-form city/area the user typed
    categories: list[str] = field(default_factory=list)
    depth: Depth = Depth.CITY

    # --- Lead rules ---
    profile: LeadProfile = LeadProfile.NO_WEBSITE
    min_rating: float = settings.MIN_RATING
    min_reviews: int = settings.MIN_REVIEWS
    require_phone: bool = settings.REQUIRE_PHONE

    # --- Depth tuning ---
    max_subareas: int = settings.MAX_SUBAREAS
    grid_rows: int = settings.GRID_ROWS
    grid_cols: int = settings.GRID_COLS
    grid_span_km: float = settings.GRID_SPAN_KM
    grid_zoom: float = settings.GRID_ZOOM
    max_results_per_unit: int | None = None      # None = whatever Google gives

    # --- Browser / network ---
    headless: bool = settings.HEADLESS
    proxy: str | None = settings.PROXY
    concurrency: int = 1

    # --- Behaviour ---
    tui: bool = True
    resume: bool = True
    fetch_website_email: bool = True             # only used when profile allows it
    output: OutputPaths = field(default_factory=default_paths)

    def __post_init__(self):
        if isinstance(self.depth, str):
            self.depth = Depth(self.depth)
        if isinstance(self.profile, str):
            self.profile = LeadProfile(self.profile)
        if isinstance(self.output, (str, Path)):
            self.output = OutputPaths(root=Path(self.output))
        self.concurrency = max(1, int(self.concurrency))

    @property
    def crawl_websites(self) -> bool:
        """Whether to open business websites hunting for email + socials."""
        return self.fetch_website_email and self.profile.needs_website_crawl

    def proxy_dict(self) -> dict | None:
        """Playwright-shaped proxy config, or None."""
        if not self.proxy:
            return None
        from urllib.parse import urlparse

        parsed = urlparse(self.proxy)
        if not parsed.hostname:
            # Bare "host:port" — hand it to Playwright as-is.
            return {"server": self.proxy}
        server = f"{parsed.scheme or 'http'}://{parsed.hostname}"
        if parsed.port:
            server += f":{parsed.port}"
        cfg: dict = {"server": server}
        if parsed.username:
            cfg["username"] = parsed.username
        if parsed.password:
            cfg["password"] = parsed.password
        return cfg
