"""Lead qualification, driven by the run's selected profile."""

import logging

from config import settings
from config.enums import LeadProfile
from data.models import Business

logger = logging.getLogger(__name__)


def is_qualified_lead(
    business: Business,
    profile: LeadProfile = LeadProfile.NO_WEBSITE,
    min_rating: float | None = None,
    min_reviews: int | None = None,
    require_phone: bool | None = None,
) -> bool:
    """Check whether a business qualifies as a lead under ``profile``.

    Shared criteria (all profiles except ALL):
      - Has a phone number, when ``require_phone``
      - Rating >= ``min_rating`` when a rating is known
      - Review count >= ``min_reviews`` when a count is known

    A missing rating or review count is not disqualifying — plenty of genuine
    small businesses have neither, and they are exactly the target here.

    Profile-specific:
      - NO_WEBSITE: business has no website at all
      - NO_EMAIL:   business has a website but no email we could find
      - ALL:        everything qualifies
    """
    if profile is LeadProfile.ALL:
        return True

    min_rating = settings.MIN_RATING if min_rating is None else min_rating
    min_reviews = settings.MIN_REVIEWS if min_reviews is None else min_reviews
    require_phone = settings.REQUIRE_PHONE if require_phone is None else require_phone

    if profile is LeadProfile.NO_WEBSITE and business.has_website:
        return False

    if profile is LeadProfile.NO_EMAIL:
        if not business.has_website:
            return False
        if business.email:
            return False

    if require_phone and not business.phone:
        return False

    if business.rating is not None and business.rating < min_rating:
        return False

    if business.review_count is not None and business.review_count < min_reviews:
        return False

    return True


def filter_qualified(
    businesses: list[Business],
    profile: LeadProfile = LeadProfile.NO_WEBSITE,
    min_rating: float | None = None,
    min_reviews: int | None = None,
    require_phone: bool | None = None,
) -> list[Business]:
    """Filter a list of businesses down to qualified leads."""
    return [
        b for b in businesses
        if is_qualified_lead(b, profile, min_rating, min_reviews, require_phone)
    ]
