"""
Zoopla scraper.

Zoopla offers a partner API: https://developer.zoopla.co.uk/
Register at their developer portal to obtain an API key.
"""

import httpx
from models import Listing, ListingSource, ListingType
from scrapers.base import BaseScraper
import os


class ZooplaScraper(BaseScraper):
    BASE_URL = "https://api.zoopla.co.uk/api/v1"

    def __init__(self):
        self.api_key = os.environ.get("ZOOPLA_API_KEY", "")

    async def scrape(self, query: str, radius_miles: int) -> list[Listing]:
        """
        Fetch rental listings from Zoopla partner API.

        Requires ZOOPLA_API_KEY environment variable.
        """
        if not self.api_key:
            print("ZOOPLA_API_KEY not set — skipping Zoopla")
            return []

        # TODO: implement Zoopla API call
        # async with httpx.AsyncClient(headers=self.HEADERS) as client:
        #     response = await client.get(
        #         f"{self.BASE_URL}/property_listings.json",
        #         params={
        #             "area": query,
        #             "radius": radius_miles,
        #             "listing_status": "rent",
        #             "api_key": self.api_key,
        #             "page_size": 100,
        #         }
        #     )
        #     response.raise_for_status()
        #     data = response.json()
        # return [self._parse(item) for item in data.get("listing", [])]

        return []  # Replace with real implementation

    def _parse(self, raw: dict) -> Listing:
        """Parse Zoopla API response into a normalized Listing."""
        return Listing(
            source=ListingSource.ZOOPLA,
            listing_type=ListingType.RENT,
            external_id=str(raw.get("listing_id", "")),
            url=raw.get("details_url", ""),
            title=raw.get("displayable_address", ""),
            address=raw.get("displayable_address", ""),
            region="",
            postcode=raw.get("postcode"),
            monthly_cost=float(raw.get("rental_prices", {}).get("per_month", 0)),
            bedrooms=raw.get("num_bedrooms", 0),
            bathrooms=raw.get("num_bathrooms"),
            square_footage=None,
            latitude=float(raw.get("latitude", 0)) or None,
            longitude=float(raw.get("longitude", 0)) or None,
            available_from=None,
            images=[raw.get("thumbnail_url", "")],
            description=raw.get("description", ""),
        )
