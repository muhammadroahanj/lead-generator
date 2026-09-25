import pytest

from geo.models import SearchUnit
from scraper.maps_scraper import (
    _build_business,
    _href_name,
    _href_signature,
    css_attr_escape,
    names_match,
)

UNIT = SearchUnit(
    category="plumbers",
    query="plumbers in Katy, TX, USA",
    city="Austin, TX, USA",
    area="Katy",
    region="TX",
)

REAL_HREF = (
    "https://www.google.com/maps/place/Beyond+Wow+Plumbing/data="
    "!4m7!3m6!1s0x8644cb2f840615a7:0x8cd2f981d6780fda"
    "!8m2!3d30.3578911!4d-97.7482485"
)


def panel(**overrides) -> dict:
    raw = {
        "panelLabel": "Beyond Wow Plumbing",
        "name": "Beyond Wow Plumbing",
        "category": "Plumber",
        "address": "3432 Greystone Dr, Austin, TX 78731, United States",
        "phone": "+1 512-601-6173",
        "websiteUrl": "https://beyondwowplumbing.com",
        "email": None,
        "plusCode": "8FVC9G8F+6W",
        "ratingText": "4.8 stars ",
        "reviewsText": "2,546 reviews",
        "hours": "Tuesday, 7 AM to 6 PM, Copy open hours",
        "priceLevel": None,
        "claimed": True,
    }
    raw.update(overrides)
    return raw


class TestBuildBusiness:
    def test_full_panel(self):
        b = _build_business(panel(), REAL_HREF, UNIT)
        assert b is not None
        assert b.name == "Beyond Wow Plumbing"
        assert b.phone == "+1 512-601-6173"
        assert b.rating == 4.8
        assert b.review_count == 2546
        assert b.has_website is True
        assert b.place_id == "0x8644cb2f840615a7:0x8cd2f981d6780fda"
        assert b.latitude == 30.3578911
        assert b.longitude == -97.7482485
        assert b.claimed is True

    def test_provenance_comes_from_the_unit(self):
        b = _build_business(panel(), REAL_HREF, UNIT)
        assert b.city == "Austin, TX, USA"
        assert b.area == "Katy"
        assert b.state == "TX"
        assert b.search_query == UNIT.query

    def test_hours_and_price_are_cleaned(self):
        b = _build_business(
            panel(priceLevel=", $1-10 per person, Reported by 50 people"), REAL_HREF, UNIT
        )
        assert b.hours == "Tuesday, 7 AM to 6 PM"
        assert b.price_level == "$1-10 per person"

    def test_nameless_panel_is_rejected(self):
        assert _build_business(panel(name=None), REAL_HREF, UNIT) is None
        assert _build_business({}, REAL_HREF, UNIT) is None

    def test_results_pane_is_rejected(self):
        # When no detail panel opens, the selector chain falls back to the
        # results pane, which would otherwise be recorded as a business
        # called "Results".
        raw = {"panelLabel": None, "name": "Results", "address": None,
               "phone": None, "websiteUrl": None, "plusCode": None}
        assert _build_business(raw, REAL_HREF, UNIT) is None

    def test_unlabelled_panel_with_real_data_is_kept(self):
        # Missing aria-label alone must not discard a genuine listing.
        raw = panel(panelLabel=None)
        assert _build_business(raw, REAL_HREF, UNIT) is not None

    def test_google_redirect_is_not_a_website(self):
        b = _build_business(panel(websiteUrl="https://www.google.com/maps"), REAL_HREF, UNIT)
        assert b.has_website is False
        assert b.website_url is None

    def test_junk_email_is_discarded(self):
        b = _build_business(panel(email="noreply@example.com"), REAL_HREF, UNIT)
        assert b.email is None

    def test_real_email_survives(self):
        b = _build_business(panel(email="hello@beyondwowplumbing.com"), REAL_HREF, UNIT)
        assert b.email == "hello@beyondwowplumbing.com"

    def test_href_without_coordinates(self):
        b = _build_business(panel(), "/maps/place/X/data=!1s0xabc:0xdef", UNIT)
        assert b.place_id == "0xabc:0xdef"
        assert b.latitude is None

    def test_maps_url_is_absolute(self):
        b = _build_business(panel(), "/maps/place/X/data=!1s0xabc:0xdef", UNIT)
        assert b.google_maps_url.startswith("https://www.google.com/maps/place/")


class TestHrefSignature:
    def test_prefers_the_place_id(self):
        assert _href_signature(REAL_HREF) == "0x8644cb2f840615a7:0x8cd2f981d6780fda"

    def test_falls_back_to_the_name_slug(self):
        assert _href_signature("/maps/place/Great+Wave+Tattoo/@1,2,17z") == "Great+Wave+Tattoo"

    def test_returns_none_when_there_is_nothing_to_match(self):
        assert _href_signature("/maps/search/tattoo") is None

    def test_signatures_differ_between_businesses(self):
        # This is what stops a stale detail panel being attributed to the
        # wrong listing: two results must never share a signature.
        a = "/maps/place/Southside+Tattoo/data=!1s0x8644b4fdbae51f73:0x3e1650a4ed7fb3da"
        b = "/maps/place/Great+Wave+Tattoo/data=!1s0x8644b5af787f716f:0x6f0d0af2c58eec34"
        assert _href_signature(a) != _href_signature(b)


class TestNamesMatch:
    @pytest.mark.parametrize("expected,actual", [
        ("Great Wave Tattoo", "Great Wave Tattoo"),
        ("Jo's Coffee - South Congress", "Jos Coffee  South Congress"),
        # Google's URL slug often carries extra marketing text.
        ("Lost Edge Tattoo | Best Tattoo Shop in Austin, TX", "Lost Edge Tattoo"),
        ("Ink Empire", "INK EMPIRE"),
    ])
    def test_matches(self, expected, actual):
        assert names_match(expected, actual)

    @pytest.mark.parametrize("expected,actual", [
        ("Great Wave Tattoo", "Southside Tattoo"),
        ("Aura IV Tattoo Gallery", "Little Pricks Tattoo"),
        ("Great Wave Tattoo", None),
        (None, "Great Wave Tattoo"),
        ("", ""),
    ])
    def test_rejects(self, expected, actual):
        assert not names_match(expected, actual)

    def test_short_names_require_exact_equality(self):
        # Containment on a tiny string would match almost anything.
        assert not names_match("Ink", "Ink Empire")
        assert names_match("Ink", "ink")


class TestHrefName:
    @pytest.mark.parametrize("href,expected", [
        ("/maps/place/Great+Wave+Tattoo/@1,2,17z", "Great Wave Tattoo"),
        ("/maps/place/Jo%27s+Coffee/data=!1s0x1:0x2", "Jo's Coffee"),
        ("/maps/search/tattoo", None),
        ("", None),
    ])
    def test_href_name(self, href, expected):
        assert _href_name(href) == expected


class TestCssEscape:
    @pytest.mark.parametrize("raw,expected", [
        ("/maps/place/X", "/maps/place/X"),
        ('a"b', 'a\\"b'),
        ("a\\b", "a\\\\b"),
    ])
    def test_escape(self, raw, expected):
        assert css_attr_escape(raw) == expected

    def test_escaped_value_is_safe_in_a_selector(self):
        href = 'https://x.com/a"b'
        selector = f'a[href="{css_attr_escape(href)}"]'
        assert selector == 'a[href="https://x.com/a\\"b"]'
