import pytest

from scraper.parsers import (
    clean_hours,
    clean_price_level,
    classify_social,
    collect_socials,
    contact_page_urls,
    email_from_mailto,
    find_emails,
    is_valid_email,
    normalize_website,
    parse_aria_field,
    parse_rating,
    parse_review_count,
)


@pytest.mark.parametrize("text,expected", [
    ("4.5", 4.5),
    ("4.5 stars", 4.5),
    ("4,5 stars", 4.5),
    ("5.0 stars 1,234 reviews", 5.0),
    ("3", 3.0),
    (None, None),
    ("", None),
    ("no rating here", None),
    ("9.9", None),          # outside the 1-5 range: wrong element
])
def test_parse_rating(text, expected):
    assert parse_rating(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("(1,234)", 1234),
    ("23 reviews", 23),
    ("1 review", 1),
    ("4.5 stars 23 reviews", 23),
    ("No reviews", None),
    (None, None),
    ("", None),
])
def test_parse_review_count(text, expected):
    assert parse_review_count(text) == expected


def test_parse_review_count_prefers_the_reviews_number():
    # The rating must not be mistaken for the review count.
    assert parse_review_count("4.5 stars 187 reviews") == 187


@pytest.mark.parametrize("aria,prefix,expected", [
    ("Address: 123 Main St", "Address:", "123 Main St"),
    ("Phone: +1 555-0100", "Phone:", "+1 555-0100"),
    ("Plus code: 8FVC9G8F+6W", "", "8FVC9G8F+6W"),
    ("No colon here", "", "No colon here"),
    (None, "", None),
])
def test_parse_aria_field(aria, prefix, expected):
    assert parse_aria_field(aria, prefix) == expected


class TestHoursAndPrice:
    @pytest.mark.parametrize("raw,expected", [
        # Google folds the button label into the same aria-label as the data.
        ("Wednesday, 7 AM to 7 PM, Copy open hours", "Wednesday, 7 AM to 7 PM"),
        ("Monday, 9 AM to 5 PM", "Monday, 9 AM to 5 PM"),
        ("Show open hours for the week", None),
        ("", None),
        (None, None),
    ])
    def test_clean_hours(self, raw, expected):
        assert clean_hours(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        (", $1-10 per person, Reported by 50 people", "$1-10 per person"),
        ("$$", "$$"),
        (", Reported by 3 people", None),
        (None, None),
    ])
    def test_clean_price_level(self, raw, expected):
        assert clean_price_level(raw) == expected


class TestEmails:
    def test_gmail_is_valid(self):
        # Free mail providers are the most common real contact address for
        # the small businesses this tool targets; blacklisting them was a bug.
        assert is_valid_email("joespizza@gmail.com")
        assert is_valid_email("info@yahoo.com")

    @pytest.mark.parametrize("email", [
        "test@example.com",
        "abc@sentry.io",
        "logo@2x.png",
        "someone@wixpress.com",
        "no-at-sign",
        "",
        None,
        "@nolocal.com",
        "1234@5678.com",     # no letters in the local part
    ])
    def test_rejects_false_positives(self, email):
        assert not is_valid_email(email)

    def test_find_emails_dedupes_and_orders(self):
        text = "Reach us at Info@Shop.com or sales@shop.com, or Info@Shop.com again."
        assert find_emails(text) == ["Info@Shop.com", "sales@shop.com"]

    def test_find_emails_skips_junk(self):
        assert find_emails("noreply@example.com and hi@realshop.co") == ["hi@realshop.co"]

    @pytest.mark.parametrize("href,expected", [
        ("mailto:hi@shop.com", "hi@shop.com"),
        ("mailto:hi@shop.com?subject=Hello", "hi@shop.com"),
        ("mailto:hi%40shop.com", "hi@shop.com"),
        ("https://shop.com", None),
        (None, None),
    ])
    def test_email_from_mailto(self, href, expected):
        assert email_from_mailto(href) == expected


class TestSocials:
    @pytest.mark.parametrize("url,expected", [
        ("https://www.facebook.com/joespizza", "facebook"),
        ("https://instagram.com/joespizza", "instagram"),
        ("https://www.linkedin.com/company/joes", "linkedin"),
        ("https://facebook.com/sharer/sharer.php?u=x", None),
        ("https://www.facebook.com/", None),          # no profile path
        ("https://twitter.com/joes", None),
        (None, None),
    ])
    def test_classify_social(self, url, expected):
        assert classify_social(url) == expected

    def test_collect_socials_keeps_first_of_each(self):
        urls = [
            "https://facebook.com/first",
            "https://facebook.com/second",
            "https://instagram.com/insta",
            "https://example.com",
        ]
        assert collect_socials(urls) == {
            "facebook": "https://facebook.com/first",
            "instagram": "https://instagram.com/insta",
        }


class TestWebsites:
    @pytest.mark.parametrize("url,expected", [
        ("https://shop.com", "https://shop.com"),
        ("shop.com", "https://shop.com"),
        ("//shop.com/x", "https://shop.com/x"),
        ("https://www.google.com/maps", None),
        ("mailto:hi@shop.com", None),
        ("javascript:void(0)", None),
        ("notaurl", None),
        (None, None),
    ])
    def test_normalize_website(self, url, expected):
        assert normalize_website(url) == expected

    def test_contact_page_urls(self):
        urls = contact_page_urls("https://shop.com/some/page", limit=2)
        assert urls == ["https://shop.com/contact", "https://shop.com/contact-us"]

    def test_contact_page_urls_rejects_garbage(self):
        assert contact_page_urls("notaurl") == []
