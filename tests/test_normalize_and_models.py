from datetime import timezone

import pytest

from data.models import Business
from data.normalize import (
    extract_postal_code,
    normalize_address,
    normalize_name,
    normalize_phone,
)


class TestNormalize:
    @pytest.mark.parametrize("a,b", [
        ("123 Main St", "123 Main Street"),
        ("123 Main St.", "123 Main Street"),
        ("45 Oak Ave", "45 Oak Avenue"),
        ("9 North Elm Blvd", "9 N Elm Boulevard"),
    ])
    def test_address_variants_collapse(self, a, b):
        assert normalize_address(a) == normalize_address(b)

    def test_different_addresses_stay_different(self):
        assert normalize_address("123 Main St") != normalize_address("124 Main St")

    @pytest.mark.parametrize("a,b", [
        ("Joe's Pizza LLC", "Joes Pizza"),
        ("ACME Inc.", "acme"),
        ("Bob & Sons, Ltd", "Bob Sons"),
    ])
    def test_name_variants_collapse(self, a, b):
        assert normalize_name(a) == normalize_name(b)

    def test_name_never_normalizes_to_nothing(self):
        # A business literally named "Co" must not become an empty key.
        assert normalize_name("Co") == "co"

    @pytest.mark.parametrize("a,b", [
        ("+1 (555) 123-4567", "555-123-4567"),
        ("555.123.4567", "5551234567"),
        ("+92 300 1234567", "03001234567"),
    ])
    def test_phone_variants_collapse(self, a, b):
        assert normalize_phone(a) == normalize_phone(b)

    def test_phone_empty(self):
        assert normalize_phone(None) == ""
        assert normalize_phone("no digits") == ""

    @pytest.mark.parametrize("address,expected", [
        ("123 Main St, Katy, TX 77494", "77494"),
        ("1 High St, London SW1A 1AA", "SW1A 1AA"),
        ("Nowhere", None),
        (None, None),
    ])
    def test_extract_postal_code(self, address, expected):
        assert extract_postal_code(address) == expected


class TestBusiness:
    def test_scraped_at_is_timezone_aware(self):
        # datetime.utcnow() was deprecated and returned a naive datetime.
        business = Business(name="X")
        assert business.scraped_at.tzinfo is not None
        assert business.scraped_at.utcoffset() == timezone.utc.utcoffset(None)

    def test_place_id_wins_as_dedup_key(self):
        a = Business(name="Joe's Pizza", place_id="0xabc:0xdef", phone="555")
        b = Business(name="Totally Different", place_id="0xabc:0xdef", phone="999")
        assert a.dedup_key == b.dedup_key

    def test_falls_back_to_name_and_phone(self):
        a = Business(name="Joe's Pizza LLC", phone="+1 (555) 123-4567")
        b = Business(name="Joes Pizza", phone="555-123-4567")
        assert a.dedup_key == b.dedup_key
        assert not a.dedup_key.startswith("pid::")

    def test_falls_back_to_address_without_phone(self):
        a = Business(name="Joe's Pizza", address="123 Main St, Katy TX")
        b = Business(name="Joes Pizza", address="123 Main Street, Katy TX")
        assert a.dedup_key == b.dedup_key

    def test_distinct_businesses_are_distinct(self):
        a = Business(name="Joe's Pizza", phone="555-1111")
        b = Business(name="Joe's Pizza", phone="555-2222")
        assert a.dedup_key != b.dedup_key

    def test_csv_dict_matches_headers(self):
        from data.exporter import CSV_HEADERS

        row = Business(name="X").to_csv_dict()
        assert list(row.keys()) == CSV_HEADERS
