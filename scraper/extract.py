"""Single-pass extraction of a Google Maps detail panel.

The previous approach probed ~8 selector chains one at a time, each with a
2-second visibility timeout. A listing missing an email, website and price
level burned 20+ seconds purely in timeouts. This reads the entire panel in
one ``page.evaluate`` round-trip instead: no per-field timeouts, no waiting on
elements that were never going to exist.
"""

import logging

from playwright.async_api import Page

from scraper.selectors import SELECTORS

logger = logging.getLogger(__name__)

# Selector chains handed to the browser. Only CSS-valid entries — Playwright's
# :has-text() pseudo-class is meaningless to querySelector.
_JS_SELECTOR_KEYS = [
    "detail_panel", "detail_name", "detail_category", "detail_address",
    "detail_phone", "detail_email", "detail_website", "detail_plus_code",
    "detail_claim",
]

DETAIL_JS = r"""
(sel) => {
  const res = {};

  const q = (root, list) => {
    for (const s of (list || [])) {
      try { const el = root.querySelector(s); if (el) return el; } catch (e) {}
    }
    return null;
  };
  const text = (el) => {
    if (!el) return null;
    const t = (el.innerText || el.textContent || '').trim();
    return t || null;
  };
  const aria = (el) => (el && el.getAttribute) ? (el.getAttribute('aria-label') || '') : '';
  const afterColon = (s) => {
    if (!s) return null;
    const i = s.indexOf(':');
    const out = (i >= 0 ? s.slice(i + 1) : s).trim();
    return out || null;
  };

  const panel = q(document, sel.detail_panel) || document.body;
  res.panelLabel = (panel.getAttribute && panel.getAttribute('aria-label')) || null;

  // --- Name ---
  res.name = text(q(panel, sel.detail_name)) || text(panel.querySelector('h1')) || res.panelLabel;

  // --- Category ---
  res.category = text(q(panel, sel.detail_category));

  // --- Address ---
  const addrEl = q(panel, sel.detail_address);
  res.address = addrEl ? (afterColon(aria(addrEl)) || text(addrEl)) : null;

  // --- Phone ---
  const phoneEl = q(panel, sel.detail_phone);
  res.phone = phoneEl ? (afterColon(aria(phoneEl)) || text(phoneEl)) : null;

  // --- Website ---
  const webEl = q(panel, sel.detail_website);
  res.websiteUrl = webEl ? (webEl.getAttribute('href') || afterColon(aria(webEl))) : null;

  // --- Email (uncommon on Maps, but free to check) ---
  const mailEl = q(panel, sel.detail_email);
  if (mailEl) {
    const href = mailEl.getAttribute('href') || '';
    res.email = href.toLowerCase().startsWith('mailto:')
      ? href.slice(7).split('?')[0]
      : (afterColon(aria(mailEl)) || text(mailEl));
  } else {
    res.email = null;
  }

  // --- Plus code ---
  const plusEl = q(panel, sel.detail_plus_code);
  res.plusCode = plusEl ? (afterColon(aria(plusEl)) || text(plusEl)) : null;

  // --- Aria-label sweep: rating, reviews, hours, price ---
  res.ratingText = null;
  res.reviewsText = null;
  res.hours = null;
  res.priceLevel = null;

  const DAYS = /(monday|tuesday|wednesday|thursday|friday|saturday|sunday)/i;
  const TIMEISH = /(\bam\b|\bpm\b|open|closed|closes|\d{1,2}:\d{2})/i;

  let labelled = [];
  try { labelled = Array.from(panel.querySelectorAll('[aria-label]')); } catch (e) {}

  for (const el of labelled) {
    const a = el.getAttribute('aria-label') || '';
    if (!a) continue;
    if (!res.ratingText && /(\d+([.,]\d+)?)\s*stars?/i.test(a)) res.ratingText = a;
    if (!res.reviewsText && /reviews?/i.test(a) && /\d/.test(a)) res.reviewsText = a;
    if (!res.hours && DAYS.test(a) && TIMEISH.test(a)) res.hours = a;
    if (!res.priceLevel) {
      const m = a.match(/price(?:\s*range)?\s*:?\s*(.+)/i);
      if (m && m[1]) res.priceLevel = m[1].trim();
    }
  }

  // Fallback: the rating block renders its number in a plain span.
  if (!res.ratingText) {
    res.ratingText = text(panel.querySelector('div.F7nice span[aria-hidden]'));
  }

  // --- Claimed status (unclaimed listings are strong leads) ---
  let claimFound = !!q(panel, sel.detail_claim);
  if (!claimFound) {
    const body = (panel.innerText || '').toLowerCase();
    claimFound = body.includes('claim this business') || body.includes('own this business');
  }
  // Only meaningful once the panel actually rendered.
  res.claimed = res.name ? !claimFound : null;

  return res;
}
"""


async def extract_detail(page: Page) -> dict:
    """Read every field off the open detail panel in one round-trip.

    Returns a dict of raw strings; parsing into typed values happens in Python
    so it stays unit-testable.
    """
    selector_subset = {key: SELECTORS[key] for key in _JS_SELECTOR_KEYS}
    try:
        return await page.evaluate(DETAIL_JS, selector_subset)
    except Exception as exc:
        logger.debug(f"Detail extraction failed: {exc}")
        return {}


WEBSITE_JS = r"""
() => {
  const out = { emails: [], links: [] };
  try {
    document.querySelectorAll('a[href]').forEach((a) => {
      const href = a.getAttribute('href') || '';
      if (href.toLowerCase().startsWith('mailto:')) out.emails.push(href);
      else if (href.startsWith('http') || href.startsWith('//')) out.links.push(href);
    });
  } catch (e) {}
  try {
    out.text = (document.body ? document.body.innerText : '') || '';
  } catch (e) { out.text = ''; }
  return out;
}
"""


async def extract_website_contacts(page: Page) -> dict:
    """Pull mailto links, outbound links and page text from a business website."""
    try:
        return await page.evaluate(WEBSITE_JS)
    except Exception as exc:
        logger.debug(f"Website extraction failed: {exc}")
        return {"emails": [], "links": [], "text": ""}
