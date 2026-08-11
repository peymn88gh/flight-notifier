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
from app.domain.types import (
    AlertCriteria,
    NormalizedItinerary,
    SiteSearchResult,
    SourceName,
    TripType,
)
from app.scrapers.adapters import build_adapters


class ScrapeBatch(BaseModel):
    itineraries: list[NormalizedItinerary] = Field(default_factory=list)
    source_status: dict[str, dict[str, Any]] = Field(default_factory=dict)


def merge_itineraries(values: list[NormalizedItinerary]) -> list[NormalizedItinerary]:
    merged: dict[str, NormalizedItinerary] = {}
    offer_keys: dict[str, set[tuple[str, str, str]]] = {}
    for itinerary in values:
        fingerprint = itinerary.fingerprint
        if fingerprint not in merged:
            merged[fingerprint] = itinerary.model_copy(deep=True)
            offer_keys[fingerprint] = {
                (offer.source.value, str(offer.amount_toman), str(offer.booking_url))
                for offer in itinerary.offers
            }
            continue
        for offer in itinerary.offers:
            key = (offer.source.value, str(offer.amount_toman), str(offer.booking_url))
            if key not in offer_keys[fingerprint]:
                merged[fingerprint].offers.append(offer)
                offer_keys[fingerprint].add(key)
    return sorted(
        merged.values(),
        key=lambda itinerary: (
            min(
                (
                    offer.amount_toman
                    for offer in itinerary.offers
                    if offer.amount_toman is not None
                ),
                default=Decimal("Infinity"),
            ),
            itinerary.outbound.departure,
        ),
    )


class ScraperManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.redis = Redis.from_url(self.settings.redis_url, decode_responses=True)

    def _date_pairs(self, criteria: AlertCriteria) -> list[tuple[date, date | None]]:
        outbound = list(iter_dates(criteria.outbound_dates.start, criteria.outbound_dates.end))
        if criteria.trip_type == TripType.ONE_WAY:
            return [(item, None) for item in outbound]
        assert criteria.return_dates is not None
        returns = list(iter_dates(criteria.return_dates.start, criteria.return_dates.end))
        return [
            (going, returning)
            for going in outbound
            for returning in returns
            if returning >= going
        ]

    def _cache_key(
        self, source: SourceName, criteria: AlertCriteria, pair: tuple[date, date | None]
    ) -> str:
        raw = json.dumps(
            {
                "source": source.value,
                "criteria": criteria.model_dump(mode="json"),
                "outbound": pair[0].isoformat(),
                "return": pair[1].isoformat() if pair[1] else None,
            },
            sort_keys=True,
        )
        return "flight-search:" + hashlib.sha256(raw.encode()).hexdigest()

    async def _cached(self, key: str) -> SiteSearchResult | None:
        try:
            value = await self.redis.get(key)
            return SiteSearchResult.model_validate_json(value) if value else None
        except Exception:
            return None

    async def _store(self, key: str, value: SiteSearchResult) -> None:
        if value.error:
            return
        try:
            ttl = max(240, self.settings.urgent_poll_minutes * 60 - 15)
            await self.redis.set(key, value.model_dump_json(), ex=ttl)
        except Exception:
            return

    async def search(self, criteria: AlertCriteria) -> ScrapeBatch:
        all_itineraries: list[NormalizedItinerary] = []
        statuses: dict[str, dict[str, Any]] = {}
        pairs = self._date_pairs(criteria)
        for adapter in build_adapters(self.settings):
            site_results: list[SiteSearchResult] = []
            async with adapter:
                for pair in pairs:
                    key = self._cache_key(adapter.source, criteria, pair)
                    result = await self._cached(key)
                    if result is None:
                        result = await adapter.search(criteria, pair[0], pair[1])
                        await self._store(key, result)
                    site_results.append(result)
            errors = [result.error for result in site_results if result.error]
            site_itineraries = [item for result in site_results for item in result.itineraries]
            all_itineraries.extend(site_itineraries)
            statuses[adapter.source.value] = {
                "ok": len(errors) == 0,
                "searches": len(site_results),
                "results": len(site_itineraries),
                "errors": errors[:3],
            }
        try:
            await self.redis.aclose()
        except Exception:
            pass
        return ScrapeBatch(
            itineraries=merge_itineraries(all_itineraries),
            source_status=statuses,
        )
