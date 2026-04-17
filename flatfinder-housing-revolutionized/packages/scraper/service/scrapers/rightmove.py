"""
Rightmove scraper.

NOTE: Rightmove's ToS prohibits scraping. Implement using one of:
  - Their official data feed (requires estate agent registration)
  - A compliant third-party aggregator API
  - A partnership agreement

This file defines the interface; fill in the HTTP implementation.
"""

import httpx
from models import Listing, ListingSource, ListingType
from scrapers.base import BaseScraper


class RightmoveScraper(BaseScraper):
    BASE_URL = "https://api.rightmove.co.uk"  # Placeholder — use official endpoint

    async def scrape(self, query: str, radius_miles: int) -> list[Listing]:
        """
        Fetch rental listings from Rightmove for the given location.

        TODO: Replace with your approved data access method.
        """
        # --- Implement your HTTP fetch here ---
        # async with httpx.AsyncClient(headers=self.HEADERS) as client:
        #     response = await client.get(
        #         f"{self.BASE_URL}/rent/search",
        #         params={"locationIdentifier": query, "radius": radius_miles}
        #     )
        #     response.raise_for_status()
        #     data = response.json()
        # return [self._parse(item) for item in data["properties"]]

        return []  # Replace with real implementation

    def _parse(self, raw: dict) -> Listing:
        """Parse a raw Rightmove API response into a normalized Listing."""
        return Listing(
            source=ListingSource.RIGHTMOVE,
            listing_type=ListingType.RENT,
            external_id=str(raw.get("id", "")),
            url=f"https://www.rightmove.co.uk/properties/{raw.get('id')}",
            title=raw.get("displayAddress", ""),
            address=raw.get("displayAddress", ""),
            region="",       # Set by caller
            postcode=raw.get("postcode"),
            monthly_cost=float(raw.get("price", {}).get("amount", 0)),
            bedrooms=raw.get("bedrooms", 0),
            bathrooms=raw.get("bathrooms"),
            square_footage=raw.get("displaySize"),
            latitude=raw.get("location", {}).get("latitude"),
            longitude=raw.get("location", {}).get("longitude"),
            available_from=None,
            images=[img.get("url", "") for img in raw.get("propertyImages", {}).get("images", [])],
            description=raw.get("summary", ""),
        )
