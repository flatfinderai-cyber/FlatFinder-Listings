"""
Base scraper interface — all source-specific scrapers implement this.
"""

from abc import ABC, abstractmethod
from models import Listing


class BaseScraper(ABC):
    """
    All scrapers must implement scrape() and return a list of Listing objects.
    Use async HTTP (httpx) to avoid blocking the FastAPI event loop.
    """

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
    }

    @abstractmethod
    async def scrape(self, query: str, radius_miles: int) -> list[Listing]:
        """
        Fetch listings from the source for the given location.

        Args:
            query: Location string (e.g. "London", "Manchester")
            radius_miles: Search radius

        Returns:
            List of normalized Listing objects
        """
        ...
