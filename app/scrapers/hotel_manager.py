from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.dates import iter_dates
from app.domain.types import HotelCriteria, HotelSearchResult, HotelSourceName, NormalizedHotel
from app.scrapers.hotel_adapters import build_hotel_adapters


class HotelScrapeBatch(BaseModel):
    hotels: list[NormalizedHotel] = Field(default_factory=list)
    source_status: dict[str, dict[str, Any]] = Field(default_factory=dict)


def merge_hotels(values: list[NormalizedHotel]) -> list[NormalizedHotel]:
    merged: dict[str, NormalizedHotel] = {}
    for hotel in values:
        fingerprint = hotel.fingerprint
        if fingerprint not in merged:
            merged[fingerprint] = hotel.model_copy(deep=True)
            merged[fingerprint].offers = []
        for offer in hotel.offers:
            existing_index = next(
                (
                    index
                    for index, existing in enumerate(merged[fingerprint].offers)
                    if existing.source == offer.source
                ),
                None,
            )
            if existing_index is None:
                merged[fingerprint].offers.append(offer.model_copy(deep=True))
                continue
            existing = merged[fingerprint].offers[existing_index]
            existing_price = existing.amount_toman or Decimal("Infinity")
            candidate_price = offer.amount_toman or Decimal("Infinity")
            if candidate_price < existing_price:
                merged[fingerprint].offers[existing_index] = offer.model_copy(deep=True)
    return sorted(
        merged.values(),
        key=lambda hotel: min(
            (offer.amount_toman for offer in hotel.offers if offer.amount_toman is not None),
            default=Decimal("Infinity"),
        ),
    )


class HotelScraperManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.redis = Redis.from_url(self.settings.redis_url, decode_responses=True)

    def _checkin_dates(self, criteria: HotelCriteria) -> list[date]:
        return list(iter_dates(criteria.checkin_dates.start, criteria.checkin_dates.end))

    def _cache_key(self, source: HotelSourceName, criteria: HotelCriteria, checkin: date) -> str:
        raw = json.dumps(
            {
                "source": source.value,
                "criteria": criteria.model_dump(mode="json"),
                "checkin": checkin.isoformat(),
            },
            sort_keys=True,
        )
        return "hotel-search:v1:" + hashlib.sha256(raw.encode()).hexdigest()

    async def _cached(self, key: str) -> HotelSearchResult | None:
        try:
            value = await self.redis.get(key)
            return HotelSearchResult.model_validate_json(value) if value else None
        except Exception:
            return None

    async def _store(self, key: str, value: HotelSearchResult) -> None:
        if value.error or not value.hotels:
            # An empty result is indistinguishable here from a transient scraping
            # glitch (the site rendered late, a selector missed, etc.). Caching it
            # would lock in a false "nothing found" for the rest of the TTL, which
            # for an alert polling on the same cadence means every following poll
            # replays the same stale miss instead of trying again.
            return
        try:
            ttl = max(240, self.settings.normal_poll_minutes * 60 - 15)
            await self.redis.set(key, value.model_dump_json(), ex=ttl)
        except Exception:
            return

    async def search(self, criteria: HotelCriteria) -> HotelScrapeBatch:
        all_hotels: list[NormalizedHotel] = []
        statuses: dict[str, dict[str, Any]] = {}
        checkin_dates = self._checkin_dates(criteria)
        for adapter in build_hotel_adapters(self.settings):
            site_results: list[HotelSearchResult] = []
            async with adapter:
                for checkin in checkin_dates:
                    key = self._cache_key(adapter.source, criteria, checkin)
                    result = await self._cached(key)
                    if result is None:
                        result = await adapter.search(criteria, checkin)
                        await self._store(key, result)
                    site_results.append(result)
            errors = [result.error for result in site_results if result.error]
            site_hotels = [item for result in site_results for item in result.hotels]
            all_hotels.extend(site_hotels)
            statuses[adapter.source.value] = {
                "ok": len(errors) == 0,
                "searches": len(site_results),
                "results": len(site_hotels),
                "errors": errors[:3],
            }
        try:
            await self.redis.aclose()
        except Exception:
            pass
        return HotelScrapeBatch(
            hotels=merge_hotels(all_hotels),
            source_status=statuses,
        )
