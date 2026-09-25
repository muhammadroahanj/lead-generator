"""Pure parsing helpers for scraped text. No browser needed — unit-tested offline."""

import re
from urllib.parse import unquote, urlparse

# --- Ratings / reviews ------------------------------------------------------

_RATING_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*star", re.IGNORECASE)
_LEADING_NUMBER_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
_REVIEWS_RE = re.compile(r"([\d,.  ]+)\s*review", re.IGNORECASE)
_ANY_NUMBER_RE = re.compile(r"[\d,.  ]+")


def _to_int(raw: str) -> int | None:
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def parse_rating(text: str | None) -> float | None:
    """Extract a rating from '4.5', '4.5 stars', or '4,5 Sterne'."""
    if not text:
        return None
    match = _RATING_RE.search(text) or _LEADING_NUMBER_RE.search(text)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    # Google ratings are 1-5. Anything else came from the wrong element.
    return value if 0.0 <= value <= 5.0 else None


def parse_review_count(text: str | None) -> int | None:
    """Extract a review count from '(1,234)', '1 234 reviews', or '23 reviews'."""
    if not text:
        return None
    match = _REVIEWS_RE.search(text)
    if match:
        return _to_int(match.group(1))
    match = _ANY_NUMBER_RE.search(text)
    return _to_int(match.group()) if match else None


def parse_aria_field(aria_value: str | None, prefix: str = "") -> str | None:
    """Strip a leading 'Label: ' from an aria-label value."""
    if not aria_value:
        return None
    value = aria_value.strip()
    if prefix and value.lower().startswith(prefix.lower()):
        value = value[len(prefix):]
    elif ":" in value:
        value = value.split(":", 1)[1]
    return value.strip() or None


# --- Hours / price ----------------------------------------------------------

# Google folds interaction affordances into the same aria-label as the data,
# e.g. "Wednesday, 7 AM to 7 PM, Copy open hours".
_HOURS_NOISE_RE = re.compile(
    r",?\s*(copy open hours|show open hours.*|hide open hours.*)$", re.IGNORECASE
)
_PRICE_NOISE_RE = re.compile(r",?\s*reported by .*$", re.IGNORECASE)
_LEADING_PUNCT_RE = re.compile(r"^[\s,:;·•-]+")


def clean_hours(text: str | None) -> str | None:
    """Strip UI affordance text out of an hours aria-label."""
    if not text:
        return None
    cleaned = _HOURS_NOISE_RE.sub("", text.strip())
    cleaned = _LEADING_PUNCT_RE.sub("", cleaned).strip().strip(",").strip()
    return cleaned or None


def clean_price_level(text: str | None) -> str | None:
    """Strip the crowd-sourcing footnote and leading punctuation from a price."""
    if not text:
        return None
    cleaned = _PRICE_NOISE_RE.sub("", text.strip())
    cleaned = _LEADING_PUNCT_RE.sub("", cleaned).strip().strip(",").strip()
    return cleaned or None


# --- Emails -----------------------------------------------------------------

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Domains that show up in page source but never belong to the business.
# NOTE: free mail providers (gmail, yahoo, hotmail, outlook) are deliberately
# NOT here — they are the most common real contact address for exactly the
# small, website-less businesses this tool targets.
EMAIL_FALSE_DOMAINS = {
    "@example.com", "@example.org", "@domain.com", "@email.com",
    "@sentry.io", "@sentry-next.wixpress.com", "@wixpress.com",
    "@schema.org", "@w3.org", "@godaddy.com", "@squarespace.com",
    "@cloudflare.com", "@yourdomain.com", "@test.com",
}
EMAIL_FALSE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
    ".ico", ".woff", ".woff2", ".ttf", ".mp4", ".pdf",
}


def is_valid_email(email: str | None) -> bool:
    """Filter out common false-positive email matches."""
    if not email or "@" not in email:
        return False
    lower = email.lower().strip()
    if any(lower.endswith(ext) for ext in EMAIL_FALSE_EXTENSIONS):
        return False
    if any(domain in lower for domain in EMAIL_FALSE_DOMAINS):
        return False
    local, _, domain = lower.partition("@")
    if not local or "." not in domain:
        return False
    # Hex blobs like "a3f9c2...@2x.png" survive the extension check when the
    # extension is stripped; require at least one letter in the local part.
    return any(ch.isalpha() for ch in local)


def find_emails(text: str | None) -> list[str]:
    """All plausible emails in a blob of text, de-duplicated, order preserved."""
    if not text:
        return []
    seen: set[str] = set()
    found: list[str] = []
    for raw in EMAIL_RE.findall(text):
        email = unquote(raw).strip().strip(".")
        lower = email.lower()
        if lower in seen or not is_valid_email(email):
            continue
        seen.add(lower)
        found.append(email)
    return found


def email_from_mailto(href: str | None) -> str | None:
    """Extract an address from a mailto: href."""
    if not href or not href.lower().startswith("mailto:"):
        return None
    email = unquote(href[7:].split("?")[0]).strip()
    return email if is_valid_email(email) else None


# --- Social links -----------------------------------------------------------

_SOCIAL_HOSTS = {
    "facebook": ("facebook.com", "fb.com", "fb.me"),
    "instagram": ("instagram.com",),
    "linkedin": ("linkedin.com",),
}
# Share widgets and platform chrome, not the business's own profile.
_SOCIAL_NOISE = (
    "/sharer", "/share", "share.php", "/plugins/", "/tr?", "intent/",
    "/login", "/signup", "/policies", "/help", "/legal",
)


def classify_social(url: str | None) -> str | None:
    """Return 'facebook' | 'instagram' | 'linkedin' for a profile URL, else None."""
    if not url:
        return None
    lowered = url.lower()
    if any(noise in lowered for noise in _SOCIAL_NOISE):
        return None
    try:
        host = urlparse(lowered if "//" in lowered else f"//{lowered}").hostname or ""
    except ValueError:
        return None
    host = host.removeprefix("www.")
    for network, hosts in _SOCIAL_HOSTS.items():
        if any(host == h or host.endswith(f".{h}") for h in hosts):
            # A bare "facebook.com" with no profile path is useless.
            path = urlparse(lowered if "//" in lowered else f"//{lowered}").path
            if path.strip("/"):
                return network
    return None


def collect_socials(urls: list[str]) -> dict[str, str]:
    """Map network -> first matching profile URL."""
    socials: dict[str, str] = {}
    for url in urls:
        network = classify_social(url)
        if network and network not in socials:
            socials[network] = url
    return socials


# --- Websites ---------------------------------------------------------------

def normalize_website(url: str | None) -> str | None:
    """Clean a website URL, rejecting Google's own redirect/search links."""
    if not url:
        return None
    url = url.strip()
    if not url or url.startswith(("mailto:", "tel:", "javascript:")):
        return None
    if not url.startswith(("http://", "https://")):
        if url.startswith("//"):
            url = f"https:{url}"
        elif "." in url.split("/")[0]:
            url = f"https://{url}"
        else:
            return None
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("google.com") or host.endswith("google.co") or host.endswith("goo.gl"):
        return None
    return url


def contact_page_urls(website_url: str, limit: int = 3) -> list[str]:
    """Likely contact pages for a site whose homepage yielded no email."""
    parsed = urlparse(website_url)
    if not parsed.scheme or not parsed.hostname:
        return []
    root = f"{parsed.scheme}://{parsed.netloc}"
    paths = ["/contact", "/contact-us", "/about", "/about-us", "/contactus"]
    return [f"{root}{path}" for path in paths[:limit]]
