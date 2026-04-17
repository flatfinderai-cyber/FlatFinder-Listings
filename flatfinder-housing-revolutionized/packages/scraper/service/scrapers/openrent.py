"""
OpenRent scraper.

OpenRent is landlord-direct and generally more accessible.
They don't have a public API — use RSS feed or careful HTTP fetching.
RSS feed: https://www.openrent.co.uk/properties-to-rent/?term=London&rss=1
"""

import httpx
import xml.etree.ElementTree as ET
from models import Listing, ListingSource, ListingType
from scrapers.base import BaseScraper


class OpenRentScraper(BaseScraper):
    RSS_URL = "https://www.openrent.co.uk/properties-to-rent/"

    async def scrape(self, query: str, radius_miles: int) -> list[Listing]:
        """Fetch listings from OpenRent via RSS feed."""
        async with httpx.AsyncClient(headers=self.HEADERS, follow_redirects=True) as client:
            try:
                response = await client.get(
                    self.RSS_URL,
                    params={"term": query, "rss": "1"},
                    timeout=30,
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                print(f"OpenRent fetch failed: {e}")
                return []

        return self._parse_rss(response.text)

    def _parse_rss(self, rss_xml: str) -> list[Listing]:
        """Parse OpenRent RSS feed into Listing objects."""
        listings = []
        try:
            root = ET.fromstring(rss_xml)
            channel = root.find("channel")
            if channel is None:
                return []

            for item in channel.findall("item"):
                listing = self._parse_item(item)
                if listing:
                    listings.append(listing)
        except ET.ParseError as e:
            print(f"OpenRent RSS parse error: {e}")

        return listings

    def _parse_item(self, item) -> Listing | None:
        """Parse a single RSS <item> into a Listing."""
        try:
            title = item.findtext("title", "")
            url = item.findtext("link", "")
            description = item.findtext("description", "")

            # Extract price from title — format: "£1,200 pcm – 2 bed flat in London"
            monthly_cost = self._extract_price(title)
            bedrooms = self._extract_bedrooms(title)
            external_id = url.split("/")[-1] if url else ""

            return Listing(
                source=ListingSource.OPENRENT,
                listing_type=ListingType.RENT,
                external_id=external_id,
                url=url,
                title=title,
                address=title,
                region="",
                postcode=None,
                monthly_cost=monthly_cost,
                bedrooms=bedrooms,
                bathrooms=None,
                square_footage=None,
                latitude=None,
                longitude=None,
                available_from=None,
                description=description,
            )
        except Exception as e:
            print(f"Failed to parse OpenRent item: {e}")
            return None

    def _extract_price(self, text: str) -> float:
        """Extract monthly cost from listing title string."""
        import re
        match = re.search(r"£([\d,]+)", text)
        if match:
            return float(match.group(1).replace(",", ""))
        return 0.0

    def _extract_bedrooms(self, text: str) -> int:
        """Extract bedroom count from listing title string."""
        import re
        match = re.search(r"(\d+)\s*bed", text, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 0
