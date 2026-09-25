"""Normalization helpers used for deduplication and area discovery.

All pure functions — covered directly by ``tests/test_normalize.py``.
"""

import re

# Street-type abbreviations. Without this, "123 Main St", "123 Main Street"
# and "123 Main St." are three distinct dedup keys for one business.
_STREET_SUFFIXES = {
    "street": "st", "st": "st",
    "avenue": "ave", "av": "ave", "ave": "ave",
    "boulevard": "blvd", "blvd": "blvd",
    "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr",
    "lane": "ln", "ln": "ln",
    "court": "ct", "ct": "ct",
    "place": "pl", "pl": "pl",
    "square": "sq", "sq": "sq",
    "parkway": "pkwy", "pkwy": "pkwy",
    "highway": "hwy", "hwy": "hwy",
    "expressway": "expy", "expy": "expy",
    "terrace": "ter", "ter": "ter",
    "circle": "cir", "cir": "cir",
    "trail": "trl", "trl": "trl",
    "suite": "ste", "ste": "ste",
    "apartment": "apt", "apt": "apt",
    "floor": "fl", "fl": "fl",
    "north": "n", "south": "s", "east": "e", "west": "w",
    "northeast": "ne", "northwest": "nw",
    "southeast": "se", "southwest": "sw",
    "saint": "st",
    "mount": "mt",
    "fort": "ft",
}

# Legal-form noise that varies between a listing's name and its own branding.
_NAME_NOISE = {
    "llc", "l.l.c", "inc", "inc.", "incorporated", "ltd", "ltd.", "limited",
    "corp", "corp.", "corporation", "co", "co.", "pvt", "pte", "plc", "gmbh",
}

# Apostrophes are *deleted* rather than turned into spaces: "Joe's Pizza" and
# "Joes Pizza" are the same business, but splitting on the apostrophe would
# give "joe s pizza" and break the match.
_APOSTROPHE_RE = re.compile(r"[''`’ʼ]")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_POSTAL_RE = re.compile(r"\b(\d{5}(?:-\d{4})?|[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2})\b")


def collapse(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    cleaned = _APOSTROPHE_RE.sub("", text.lower())
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    return _WS_RE.sub(" ", cleaned).strip()


def normalize_name(name: str | None) -> str:
    """Normalize a business name for comparison."""
    base = collapse(name or "")
    if not base:
        return ""
    tokens = [t for t in base.split(" ") if t not in _NAME_NOISE]
    # Never normalize a name out of existence (e.g. a business literally named "Co").
    return " ".join(tokens) if tokens else base


def normalize_phone(phone: str | None) -> str:
    """Reduce a phone number to comparable digits.

    Keeps the last 10 digits when the number is long enough, so that
    "+1 (555) 123-4567" and "555-123-4567" — and the international/local
    spellings of the same number — collapse to one key.
    """
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return ""
    return digits[-10:] if len(digits) > 10 else digits


def normalize_address(address: str | None) -> str:
    """Normalize an address for comparison, expanding street-type variants."""
    base = collapse(address or "")
    if not base:
        return ""
    tokens = [_STREET_SUFFIXES.get(tok, tok) for tok in base.split(" ")]
    return " ".join(tokens)


def extract_postal_code(address: str | None) -> str | None:
    """Pull a US ZIP or UK-style postcode out of an address, if present."""
    if not address:
        return None
    match = _POSTAL_RE.search(address.upper())
    return match.group(1) if match else None


def address_parts(address: str | None) -> list[str]:
    """Split an address into trimmed comma-separated components."""
    if not address:
        return []
    return [part.strip() for part in address.split(",") if part.strip()]
