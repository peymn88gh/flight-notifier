import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from app.domain.types import HotelSearchResult, HotelSourceName, SiteSearchResult, SourceName
from app.scrapers.hotel_manager import HotelScraperManager
from app.scrapers.manager import ScraperManager


def test_hotel_manager_does_not_cache_empty_results() -> None:
    manager = HotelScraperManager.__new__(HotelScraperManager)
    manager.redis = AsyncMock()
    empty = HotelSearchResult(
        source=HotelSourceName.SNAPPTRIP,
        hotels=[],
        searched_at=datetime.now(UTC),
        search_url="https://www.snapptrip.com/international-hotel/istanbul-tr",
    )
    asyncio.run(HotelScraperManager._store(manager, "key", empty))
    manager.redis.set.assert_not_called()


def test_flight_manager_does_not_cache_empty_results() -> None:
    manager = ScraperManager.__new__(ScraperManager)
    manager.redis = AsyncMock()
    empty = SiteSearchResult(
        source=SourceName.ALIBABA,
        itineraries=[],
        searched_at=datetime.now(UTC),
        search_url="https://www.alibaba.ir/flights/THR-MHD",
    )
    asyncio.run(ScraperManager._store(manager, "key", empty))
    manager.redis.set.assert_not_called()
