"""
Centralized Google Maps selectors.

ALL CSS selectors and aria-label patterns live here. When Google changes its
DOM, update THIS file only — then run ``python main.py --doctor`` to confirm
what still matches.

Strategy: prefer semantic attributes that Google needs for accessibility
(``role``, ``aria-label``, ``data-item-id``) over obfuscated CSS classes like
``a.hfpxzc``, which rotate on Google's release cadence. Obfuscated classes are
kept as *last* entries in each chain, never as the only entry.

Every consumer must walk the whole chain. Reading ``SELECTORS[key][0]`` throws
away the fallbacks and turns a class rotation into a silent zero-result run.
"""

SELECTORS = {
    # --- Results List ---
    "results_feed": [
        'div[role="feed"]',
        'div[aria-label^="Results for"]',
        "div.m6QErb.DxyBCb.kA9KIf.dS8AEf",
    ],
    "result_link": [
        'a[href*="/maps/place/"]',
        "a.hfpxzc",
    ],

    # --- Detail Panel ---
    # The detail pane is a role="main" region labelled with the business name.
    "detail_panel": [
        'div[role="main"][aria-label]:not([aria-label^="Results for"])',
        'div[role="main"]',
    ],
    "detail_name": [
        'div[role="main"] h1',
        "h1.DUwDvf",
        "h1.fontHeadlineLarge",
    ],
    "detail_address": [
        'button[data-item-id="address"]',
        '*[aria-label^="Address:"]',
        'button[data-tooltip="Copy address"]',
    ],
    "detail_phone": [
        'button[data-item-id^="phone"]',
        '*[aria-label^="Phone:"]',
        'button[data-tooltip="Copy phone number"]',
    ],
    "detail_email": [
        'button[data-item-id^="email"]',
        '*[aria-label^="Email:"]',
        'a[href^="mailto:"]',
    ],
    "detail_website": [
        'a[data-item-id="authority"]',
        '*[aria-label^="Website:"]',
        '*[data-tooltip="Open website"]',
    ],
    "detail_plus_code": [
        'button[data-item-id="oloc"]',
        '*[aria-label^="Plus code:"]',
    ],
    "detail_hours": [
        '*[aria-label*="Hours"]',
        'div[jsaction*="openhours"]',
        "div.t39EBf",
    ],
    "detail_rating": [
        'div[role="img"][aria-label*="stars"]',
        "div.F7nice span[aria-hidden]",
        'span[aria-label*="stars"]',
    ],
    "detail_reviews_count": [
        'button[aria-label*="reviews"]',
        'span[aria-label*="reviews"]',
        'div.F7nice span[aria-label]',
    ],
    "detail_category": [
        'button[jsaction*="category"]',
        "span.DkEaL",
    ],
    "detail_claim": [
        'a[href*="/business/"][aria-label*="Claim"]',
        '*[aria-label*="Claim this business"]',
    ],

    # --- Detail Panel Load Signal ---
    # A bare "h1" matches almost anything, so it is deliberately absent here:
    # it used to let a half-loaded or wrong panel report as ready.
    "detail_loaded": [
        'div[role="main"][aria-label] h1',
        'button[data-item-id="address"]',
        'button[data-item-id^="phone"]',
        "h1.DUwDvf",
    ],

    # --- Scroll End Detection ---
    "end_of_list": [
        'span:has-text("You\'ve reached the end of the list")',
        "span.HlvSq",
        'p.fontBodyMedium:has-text("end of the list")',
    ],

    # --- Search Box (used to read back what Maps resolved a place to) ---
    "search_box": [
        "input#searchboxinput",
        'input[name="q"]',
    ],

    # --- CAPTCHA / Block Detection ---
    "captcha_indicator": [
        'iframe[src*="recaptcha"]',
        'iframe[src*="sorry/index"]',
        "#recaptcha",
        'form[action*="sorry"]',
    ],
    "block_indicator_text": [
        "unusual traffic",
        "automated queries",
        "not a robot",
        "systems have detected",
    ],
}

# Selectors that --doctor treats as fatal when missing: without them the
# scraper cannot function at all. The rest are per-business fields that are
# legitimately absent on many listings.
CRITICAL_SELECTOR_KEYS = ["results_feed", "result_link", "detail_panel", "detail_loaded"]
