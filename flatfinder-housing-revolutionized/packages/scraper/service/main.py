"""
FlatFinder Scraper Service
FastAPI app called by the Cloudflare Agent scheduler.
"""

import asyncio
from fastapi import FastAPI, HTTPException
from scrapers.rightmove import RightmoveScraper
from scrapers.zoopla import ZooplaScraper
from scrapers.openrent import OpenRentScraper
from models import Listing

app = FastAPI(title="FlatFinder Scraper Service", version="0.1.0")

SCRAPERS = {
    "rightmove": RightmoveScraper,
    "zoopla": ZooplaScraper,
    "openrent": OpenRentScraper,
}

REGIONS = {
    "london": {"query": "London", "radius_miles": 10},
    "manchester": {"query": "Manchester", "radius_miles": 5},
    "birmingham": {"query": "Birmingham", "radius_miles": 5},
    "edinburgh": {"query": "Edinburgh", "radius_miles": 5},
    "bristol": {"query": "Bristol", "radius_miles": 5},
}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scrape/{region}")
async def scrape_region(region: str):
    if region not in REGIONS:
        raise HTTPException(status_code=404, detail=f"Unknown region: {region}")

    region_config = REGIONS[region]
    all_listings: list[Listing] = []

    # Run all scrapers concurrently
    tasks = [
        scraper_class().scrape(
            query=region_config["query"],
            radius_miles=region_config["radius_miles"],
        )
        for scraper_class in SCRAPERS.values()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            # Don't fail the whole cycle if one source fails
            print(f"Scraper error: {result}")
            continue
        all_listings.extend(result)

    # TODO: write to Supabase (packages/database integration)
    print(f"[{region}] Found {len(all_listings)} listings")

    return {
        "region": region,
        "listings_found": len(all_listings),
        "listings": [l.to_dict() for l in all_listings],
    }


@app.get("/regions")
async def list_regions():
    return {"regions": list(REGIONS.keys())}
