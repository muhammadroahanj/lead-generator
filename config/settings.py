"""Global settings and tunables for the scraper.

Every value here can be overridden with an environment variable using the
``SCRAPER_`` prefix, e.g. ``SCRAPER_SEARCH_DELAY_MIN=8`` or
``SCRAPER_HEADLESS=1``. This keeps Docker/CI runs configurable without editing
source.

Note: modules that need values which change at *runtime* (thresholds, headless,
proxy) should read them from ``config.runconfig.RunConfig`` instead — importing
a constant from here binds it by value at import time.
"""

import os
from pathlib import Path


# --- Env override helpers ---------------------------------------------------

def _env(name: str) -> str | None:
    return os.environ.get(f"SCRAPER_{name}")


def _env_str(name: str, default: str | None) -> str | None:
    raw = _env(name)
    return raw if raw not in (None, "") else default


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


# --- Paths ---
BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = Path(_env_str("OUTPUT_DIR", str(BASE_DIR / "output")))

# --- Browser ---
HEADLESS = _env_bool("HEADLESS", False)  # Headful mode is less detected
PROXY = _env_str("PROXY", None)  # e.g. http://user:pass@host:port
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
]

# --- Anti-Detection Delays (seconds) ---
SCROLL_DELAY_MIN = _env_float("SCROLL_DELAY_MIN", 1.5)
SCROLL_DELAY_MAX = _env_float("SCROLL_DELAY_MAX", 3.5)
DETAIL_DELAY_MIN = _env_float("DETAIL_DELAY_MIN", 1.2)
DETAIL_DELAY_MAX = _env_float("DETAIL_DELAY_MAX", 2.8)
SEARCH_DELAY_MIN = _env_float("SEARCH_DELAY_MIN", 5.0)
SEARCH_DELAY_MAX = _env_float("SEARCH_DELAY_MAX", 10.0)
CITY_BREAK_MIN = _env_float("CITY_BREAK_MIN", 30.0)
CITY_BREAK_MAX = _env_float("CITY_BREAK_MAX", 60.0)
IDLE_PAUSE_MIN = _env_float("IDLE_PAUSE_MIN", 10.0)
IDLE_PAUSE_MAX = _env_float("IDLE_PAUSE_MAX", 30.0)
IDLE_PAUSE_EVERY = (
    _env_int("IDLE_PAUSE_EVERY_MIN", 12),
    _env_int("IDLE_PAUSE_EVERY_MAX", 25),
)  # random range: take idle pause every N actions

# --- Viewport Randomization ---
VIEWPORT_WIDTH_RANGE = (1280, 1920)
VIEWPORT_HEIGHT_RANGE = (800, 1080)

# --- Session Management ---
CONTEXT_REFRESH_EVERY = _env_int("CONTEXT_REFRESH_EVERY", 120)  # detail visits
CAPTCHA_PAUSE_SECONDS = _env_float("CAPTCHA_PAUSE_SECONDS", 300)
MAX_CONSECUTIVE_BLOCKS = _env_int("MAX_CONSECUTIVE_BLOCKS", 4)  # then abort
BLOCK_CHECK_EVERY = _env_int("BLOCK_CHECK_EVERY", 15)  # results between checks

# --- Retries ---
RETRY_ATTEMPTS = _env_int("RETRY_ATTEMPTS", 3)
RETRY_BASE_DELAY = _env_float("RETRY_BASE_DELAY", 2.0)
RETRY_FACTOR = _env_float("RETRY_FACTOR", 2.0)

# --- Scraping Limits ---
MAX_SCROLLS_PER_SEARCH = _env_int("MAX_SCROLLS_PER_SEARCH", 30)
SCROLL_NO_NEW_RESULTS_LIMIT = _env_int("SCROLL_NO_NEW_RESULTS_LIMIT", 4)
DETAIL_LOAD_TIMEOUT_MS = _env_int("DETAIL_LOAD_TIMEOUT_MS", 10000)
RESULTS_FEED_TIMEOUT_MS = _env_int("RESULTS_FEED_TIMEOUT_MS", 20000)
ELEMENT_CHECK_TIMEOUT_MS = _env_int("ELEMENT_CHECK_TIMEOUT_MS", 1500)
NAV_TIMEOUT_MS = _env_int("NAV_TIMEOUT_MS", 45000)
WEBSITE_TIMEOUT_MS = _env_int("WEBSITE_TIMEOUT_MS", 8000)

# --- Lead Qualification (defaults; overridable per run via RunConfig) ---
MIN_RATING = _env_float("MIN_RATING", 3.0)
MIN_REVIEWS = _env_int("MIN_REVIEWS", 5)
REQUIRE_PHONE = _env_bool("REQUIRE_PHONE", True)

# --- Persistence ---
CHECKPOINT_EVERY = _env_int("CHECKPOINT_EVERY", 10)  # results between checkpoints
DEDUP_SAVE_EVERY = _env_int("DEDUP_SAVE_EVERY", 25)  # records between dedup saves
CSV_FLUSH_EVERY = _env_int("CSV_FLUSH_EVERY", 10)  # records between CSV flushes

# --- Default target (mainly for Docker/CI, where there is no wizard) ---
# e.g. SCRAPER_CITY="Austin TX" SCRAPER_DEPTH=areas SCRAPER_CATEGORIES="plumbers,dentists"
CITY = _env_str("CITY", None)
DEPTH = _env_str("DEPTH", None)
_raw_categories = _env_str("CATEGORIES", None)
CATEGORIES_OVERRIDE = (
    [c.strip() for c in _raw_categories.split(",") if c.strip()]
    if _raw_categories else None
)

# --- Geography ---
MAX_SUBAREAS = _env_int("MAX_SUBAREAS", 12)
GRID_ROWS = _env_int("GRID_ROWS", 3)
GRID_COLS = _env_int("GRID_COLS", 3)
GRID_SPAN_KM = _env_float("GRID_SPAN_KM", 18.0)
GRID_ZOOM = _env_float("GRID_ZOOM", 14.0)

# --- User Agents ---
# Chromium-only on purpose: Playwright drives Chromium, so a Firefox or Safari
# UA string contradicts the real JS/TLS fingerprint and is worse than no
# override at all.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
]

# --- Locale / timezone guesses by rough longitude band -----------------------
# Used to keep the browser fingerprint consistent with the area being scraped
# instead of claiming America/New_York while searching Seattle or Lahore.
TIMEZONE_BANDS = [
    (-180.0, -140.0, "Pacific/Honolulu"),
    (-140.0, -115.0, "America/Los_Angeles"),
    (-115.0, -100.0, "America/Denver"),
    (-100.0, -85.0, "America/Chicago"),
    (-85.0, -50.0, "America/New_York"),
    (-50.0, -20.0, "America/Sao_Paulo"),
    (-20.0, 5.0, "Europe/London"),
    (5.0, 25.0, "Europe/Berlin"),
    (25.0, 45.0, "Europe/Istanbul"),
    (45.0, 62.0, "Asia/Dubai"),
    (62.0, 82.0, "Asia/Karachi"),
    (82.0, 100.0, "Asia/Kolkata"),
    (100.0, 122.0, "Asia/Singapore"),
    (122.0, 145.0, "Asia/Tokyo"),
    (145.0, 180.0, "Australia/Sydney"),
]
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_LOCALE = "en-US"


def timezone_for_longitude(lng: float | None) -> str:
    """Best-effort IANA timezone for a longitude. Falls back to the default."""
    if lng is None:
        return DEFAULT_TIMEZONE
    for low, high, tz in TIMEZONE_BANDS:
        if low <= lng < high:
            return tz
    return DEFAULT_TIMEZONE
