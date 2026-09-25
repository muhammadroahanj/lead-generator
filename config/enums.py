"""Enums shared across config, geo, data and UI layers.

Kept in their own module so `config.runconfig`, `data.qualifier` and `geo.plan`
can all import them without creating an import cycle.
"""

from enum import Enum


class Depth(str, Enum):
    """How finely a target city is subdivided before searching.

    Google Maps returns at most ~120 results per query, so the only way to get
    more businesses out of one city is to issue more, narrower queries.
    """

    CITY = "city"    # One query per category: "<category> in <city>"
    AREAS = "areas"  # One query per (discovered sub-area x category)
    GRID = "grid"    # One query per (lat/lng tile x category)

    @property
    def label(self) -> str:
        return {
            Depth.CITY: "City only",
            Depth.AREAS: "Sub-areas (recommended)",
            Depth.GRID: "Coordinate grid (max coverage)",
        }[self]

    @property
    def blurb(self) -> str:
        return {
            Depth.CITY: "1 query per category. Fastest, caps at ~120 results per category.",
            Depth.AREAS: "Splits the city into suburbs/postal areas discovered from Maps itself. Typically 5-15x more results.",
            Depth.GRID: "Tiles the city with lat/lng cells. Highest coverage, longest run.",
        }[self]


class LeadProfile(str, Enum):
    """Which businesses count as a qualified lead."""

    NO_WEBSITE = "no_website"  # Digitally underserved: no site at all
    NO_EMAIL = "no_email"      # Has a site, but no email we could find
    ALL = "all"                # Everything qualifies; filter later

    @property
    def label(self) -> str:
        return {
            LeadProfile.NO_WEBSITE: "No website (default)",
            LeadProfile.NO_EMAIL: "Has website but no discoverable email",
            LeadProfile.ALL: "All businesses",
        }[self]

    @property
    def blurb(self) -> str:
        return {
            LeadProfile.NO_WEBSITE: "Businesses with no website at all. Classic 'build them a site' outreach.",
            LeadProfile.NO_EMAIL: "Businesses with a site but no reachable email. Crawls the site for contact details.",
            LeadProfile.ALL: "Qualify nothing; export every business found.",
        }[self]

    @property
    def needs_website_crawl(self) -> bool:
        """Whether visiting the business website can change the outcome.

        Under NO_WEBSITE a business with a site is rejected outright, so
        crawling it is pure wasted time.
        """
        return self is not LeadProfile.NO_WEBSITE
