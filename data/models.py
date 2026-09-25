"""Data models for scraped business leads."""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from data.normalize import normalize_address, normalize_name, normalize_phone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Business(BaseModel):
    """A business scraped from Google Maps."""

    # --- Identity ---
    name: str
    place_id: Optional[str] = None       # from the result href; exact identity
    category: Optional[str] = None

    # --- Contact ---
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    has_website: bool = False
    website_url: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    linkedin: Optional[str] = None

    # --- Reputation ---
    rating: Optional[float] = None
    review_count: Optional[int] = None
    claimed: Optional[bool] = None       # None = could not determine

    # --- Location ---
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    plus_code: Optional[str] = None
    city: str = ""
    area: Optional[str] = None
    metro_area: str = ""
    state: Optional[str] = None

    # --- Extras ---
    hours: Optional[str] = None
    price_level: Optional[str] = None
    google_maps_url: Optional[str] = None

    # --- Provenance ---
    search_query: str = ""
    scraped_at: datetime = Field(default_factory=_utcnow)

    @property
    def dedup_key(self) -> str:
        """Stable identity for deduplication.

        Google's place id is exact and free (it is embedded in the result
        href), so prefer it. Otherwise fall back to a normalized
        name + phone/address composite.
        """
        if self.place_id:
            return f"pid::{self.place_id}"

        name = normalize_name(self.name)
        phone = normalize_phone(self.phone)
        secondary = phone or normalize_address(self.address)
        return f"{name}::{secondary}"

    def to_csv_dict(self) -> dict:
        """Convert to a flat dict suitable for CSV/XLSX export."""
        return {
            "Name": self.name,
            "Category": self.category or "",
            "Address": self.address or "",
            "Phone": self.phone or "",
            "Business Email": self.email or "",
            "Rating": self.rating if self.rating is not None else "",
            "Reviews": self.review_count if self.review_count is not None else "",
            "Has Website": "Yes" if self.has_website else "No",
            "Website URL": self.website_url or "",
            "Facebook": self.facebook or "",
            "Instagram": self.instagram or "",
            "LinkedIn": self.linkedin or "",
            "Claimed": "" if self.claimed is None else ("Yes" if self.claimed else "No"),
            "Hours": self.hours or "",
            "Price Level": self.price_level or "",
            "Latitude": self.latitude if self.latitude is not None else "",
            "Longitude": self.longitude if self.longitude is not None else "",
            "Plus Code": self.plus_code or "",
            "Place ID": self.place_id or "",
            "Google Maps URL": self.google_maps_url or "",
            "City": self.city,
            "Area": self.area or "",
            "Metro Area": self.metro_area,
            "State": self.state or "",
            "Search Query": self.search_query,
            "Scraped At": self.scraped_at.isoformat(),
        }
