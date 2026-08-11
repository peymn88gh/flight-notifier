import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import Alert, User
from app.db.repositories import UserRepository
from app.domain.types import FlightLeg, NormalizedItinerary, SellerOffer
from app.scrapers.manager import ScrapeBatch
from app.services.results import reconcile_offer_states


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as value:
        yield value
    await engine.dispose()


@pytest.mark.asyncio
async def test_phone_allowlist_binding_is_unique(session) -> None:
    user = User(phone_e164="+989396451429", is_allowed=True)
    session.add(user)
    await session.commit()
    bound = await UserRepository(session).bind_contact(
        phone_e164=user.phone_e164,
        telegram_user_id=42,
        telegram_chat_id=42,
        username="tester",
        first_name="Test",
        last_name=None,
    )
    assert bound.telegram_user_id == 42

    other = User(phone_e164="+989121234567", is_allowed=True, telegram_user_id=99)
    session.add(other)
    await session.commit()
    with pytest.raises(PermissionError):
        await UserRepository(session).bind_contact(
            phone_e164=other.phone_e164,
            telegram_user_id=100,
            telegram_chat_id=100,
            username=None,
            first_name="Other",
            last_name=None,
        )


def result(amount: int) -> NormalizedItinerary:
    observed = datetime(2026, 8, 11, tzinfo=UTC)
    return NormalizedItinerary(
        outbound=FlightLeg(
            origin="THR",
            destination="MHD",
            departure="2026-08-30T18:00:00+03:30",
            airline="Mahan Air",
            flight_number="W51020",
        ),
        offers=[
            SellerOffer(
                source="trip",
                amount=Decimal(amount),
                amount_toman=Decimal(amount),
                currency="IRT",
                price_kind="total",
                booking_url="https://trip.ir/flight/booking/search",
                observed_at=observed,
            )
        ],
    )


@pytest.mark.asyncio
async def test_changes_require_two_successful_misses_for_removal(session) -> None:
    user = User(phone_e164="+989396451429", is_allowed=True)
    session.add(user)
    await session.flush()
    alert = Alert(
        id=uuid.uuid4(),
        user_id=user.id,
        criteria={},
        expires_at=datetime(2026, 9, 1, tzinfo=UTC),
        next_run_at=datetime(2026, 8, 11, tzinfo=UTC),
    )
    session.add(alert)
    await session.flush()

    available = ScrapeBatch(
        itineraries=[result(9_000_000)],
        source_status={"trip": {"ok": True, "results": 1}},
    )
    first = await reconcile_offer_states(session, alert.id, available)
    assert first.added == 1
    await session.commit()

    changed = await reconcile_offer_states(
        session,
        alert.id,
        ScrapeBatch(
            itineraries=[result(8_500_000)],
            source_status={"trip": {"ok": True, "results": 1}},
        ),
    )
    assert changed.changed == 1
    await session.commit()

    missing = ScrapeBatch(source_status={"trip": {"ok": True, "results": 0}})
    first_miss = await reconcile_offer_states(session, alert.id, missing)
    assert first_miss.removed == 0
    await session.commit()
    second_miss = await reconcile_offer_states(session, alert.id, missing)
    assert second_miss.removed == 1

