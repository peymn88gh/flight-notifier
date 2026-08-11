from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OfferState, utc_now
from app.domain.types import NormalizedItinerary
from app.scrapers.manager import ScrapeBatch


@dataclass(frozen=True)
class ChangeSet:
    added: int = 0
    changed: int = 0
    removed: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.removed)

    def as_dict(self) -> dict[str, int]:
        return {"added": self.added, "changed": self.changed, "removed": self.removed}


def _offer_key(itinerary: NormalizedItinerary, source: str) -> str:
    return f"{itinerary.fingerprint}:{source}"


def _offer_payload(itinerary: NormalizedItinerary, offer) -> dict[str, Any]:
    return {
        "itinerary": itinerary.fingerprint,
        "source": offer.source.value,
        "amount_toman": str(offer.amount_toman) if offer.amount_toman is not None else None,
        "currency": offer.currency,
        "price_kind": offer.price_kind.value,
        "seats_remaining": offer.seats_remaining,
    }


def snapshot_payload(batch: ScrapeBatch) -> dict[str, Any]:
    return {
        "itineraries": [item.model_dump(mode="json") for item in batch.itineraries],
        "source_status": batch.source_status,
    }


def snapshot_digest(batch: ScrapeBatch) -> str:
    stable = {
        "itineraries": [
            {
                "fingerprint": item.fingerprint,
                "offers": sorted(
                    [
                        {
                            "source": offer.source.value,
                            "amount_toman": str(offer.amount_toman),
                            "currency": offer.currency,
                            "price_kind": offer.price_kind.value,
                            "seats": offer.seats_remaining,
                        }
                        for offer in item.offers
                    ],
                    key=lambda value: (value["source"], value["amount_toman"]),
                ),
            }
            for item in batch.itineraries
        ],
    }
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


async def reconcile_offer_states(
    session: AsyncSession,
    alert_id: uuid.UUID,
    batch: ScrapeBatch,
) -> ChangeSet:
    states = list(
        await session.scalars(select(OfferState).where(OfferState.alert_id == alert_id))
    )
    by_key = {state.fingerprint: state for state in states}
    seen: set[str] = set()
    added = changed = removed = 0
    now = utc_now()

    for itinerary in batch.itineraries:
        for offer in itinerary.offers:
            key = _offer_key(itinerary, offer.source.value)
            payload = _offer_payload(itinerary, offer)
            seen.add(key)
            state = by_key.get(key)
            if state is None:
                session.add(
                    OfferState(
                        alert_id=alert_id,
                        fingerprint=key,
                        payload=payload,
                        active=True,
                        miss_count=0,
                        first_seen_at=now,
                        last_seen_at=now,
                    )
                )
                added += 1
            else:
                if not state.active:
                    added += 1
                elif state.payload != payload:
                    changed += 1
                state.payload = payload
                state.active = True
                state.miss_count = 0
                state.last_seen_at = now

    successful_sources = {
        source for source, status in batch.source_status.items() if status.get("ok", False)
    }
    for key, state in by_key.items():
        if key in seen or not state.active:
            continue
        state_source = str(state.payload.get("source", ""))
        if state_source not in successful_sources:
            continue
        state.miss_count += 1
        if state.miss_count >= 2:
            state.active = False
            removed += 1

    await session.flush()
    return ChangeSet(added=added, changed=changed, removed=removed)
