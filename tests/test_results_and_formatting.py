import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.bot.formatting import render_snapshot_page
from app.domain.types import FlightLeg, NormalizedItinerary, SellerOffer
from app.scrapers.manager import ScrapeBatch, merge_itineraries
from app.services.results import snapshot_digest


def itinerary(source: str, amount: int, hour: int = 18) -> NormalizedItinerary:
    observed = datetime(2026, 8, 11, tzinfo=UTC)
    return NormalizedItinerary(
        outbound=FlightLeg(
            origin="THR",
            destination="MHD",
            departure=datetime(2026, 8, 30, hour, 0, tzinfo=UTC),
            arrival=datetime(2026, 8, 30, hour + 1, 20, tzinfo=UTC),
            airline="Mahan Air",
            flight_number="W51020",
        ),
        offers=[
            SellerOffer(
                source=source,
                amount=Decimal(amount),
                amount_toman=Decimal(amount),
                currency="IRT",
                price_kind="total",
                booking_url=f"https://{source if source != 'respina24' else 'respina24'}.ir/offer",
                observed_at=observed,
            )
        ],
    )


def test_merge_groups_same_itinerary_and_preserves_sellers() -> None:
    first = itinerary("alibaba", 10_000_000)
    second = itinerary("trip", 9_000_000)
    values = merge_itineraries([first, second])
    assert len(values) == 1
    assert {offer.source.value for offer in values[0].offers} == {"alibaba", "trip"}


def test_snapshot_digest_ignores_observation_time() -> None:
    first = itinerary("trip", 9_000_000)
    second = first.model_copy(deep=True)
    second.offers[0].observed_at += timedelta(hours=1)
    assert snapshot_digest(ScrapeBatch(itineraries=[first])) == snapshot_digest(
        ScrapeBatch(itineraries=[second])
    )


def test_snapshot_digest_ignores_source_health_changes() -> None:
    value = itinerary("trip", 9_000_000)
    healthy = ScrapeBatch(
        itineraries=[value],
        source_status={"trip": {"ok": True, "results": 1}},
    )
    degraded = ScrapeBatch(
        itineraries=[value],
        source_status={"trip": {"ok": False, "results": 1, "errors": ["timeout"]}},
    )
    assert snapshot_digest(healthy) == snapshot_digest(degraded)


def test_pagination_edits_one_message_snapshot() -> None:
    values = [itinerary("trip", 9_000_000, 18), itinerary("alibaba", 10_000_000, 20)]
    snapshot_id = uuid.uuid4()
    text, keyboard = render_snapshot_page(
        snapshot_id=snapshot_id,
        alert_id=uuid.uuid4(),
        itineraries=values,
        page=0,
    )
    callback_values = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "1" in text and "2" in text
    assert any(value and value.startswith(f"pg:{snapshot_id}:1") for value in callback_values)
