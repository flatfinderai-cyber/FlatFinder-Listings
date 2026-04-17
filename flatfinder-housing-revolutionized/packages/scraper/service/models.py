from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ListingSource(str, Enum):
    RIGHTMOVE = "rightmove"
    ZOOPLA = "zoopla"
    OPENRENT = "openrent"
    SPAREROOM = "spareroom"
    ON_THE_MARKET = "on_the_market"


class ListingType(str, Enum):
    RENT = "rent"
    BUY = "buy"


@dataclass
class Listing:
    source: ListingSource
    listing_type: ListingType
    external_id: str         # Source-specific unique ID
    url: str

    title: str
    address: str
    region: str
    postcode: str | None

    monthly_cost: float      # Rent/month OR estimated mortgage/month
    bedrooms: int
    bathrooms: int | None
    square_footage: int | None

    latitude: float | None
    longitude: float | None

    available_from: datetime | None
    listed_at: datetime = field(default_factory=datetime.utcnow)
    images: list[str] = field(default_factory=list)
    description: str = ""

    # Set by the algorithm package — not the scraper
    affordability_score: float | None = None
    qualifies_40_percent: bool | None = None

    def to_dict(self) -> dict:
        return {
            "source": self.source.value,
            "listing_type": self.listing_type.value,
            "external_id": self.external_id,
            "url": self.url,
            "title": self.title,
            "address": self.address,
            "region": self.region,
            "postcode": self.postcode,
            "monthly_cost": self.monthly_cost,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "square_footage": self.square_footage,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "available_from": self.available_from.isoformat() if self.available_from else None,
            "listed_at": self.listed_at.isoformat(),
            "images": self.images,
            "description": self.description,
        }
