from __future__ import annotations

import asyncio
import random
import uuid
from datetime import datetime, timedelta

from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.formatting import render_snapshot_page
from app.bot.runtime import get_bot
from app.core.config import get_settings
from app.db.base import SessionFactory
from app.db.models import Alert, ResultSnapshot, ScrapeRun, utc_now
from app.domain.types import AlertCriteria, AlertStatus, NormalizedItinerary
from app.scrapers import ScraperManager
from app.services.results import reconcile_offer_states, snapshot_digest, snapshot_payload
from app.worker.celery_app import celery_app

settings = get_settings()


def next_run_time(alert: Alert, now: datetime) -> datetime:
    remaining = alert.expires_at - now
    minutes = (
        settings.urgent_poll_minutes
        if remaining <= timedelta(hours=settings.urgent_window_hours)
        else settings.normal_poll_minutes
    )
    return now + timedelta(minutes=minutes, seconds=random.randint(0, 30))


async def _dispatch_due_alerts() -> int:
    now = utc_now()
    async with SessionFactory() as session:
        alerts = list(
            await session.scalars(
                select(Alert)
                .where(
                    Alert.status == AlertStatus.ACTIVE.value,
                    Alert.next_run_at <= now,
                )
                .limit(100)
            )
        )
        ids: list[str] = []
        for alert in alerts:
            # Claim the alert before queueing so two scheduler instances cannot overlap it.
            alert.next_run_at = now + timedelta(minutes=settings.normal_poll_minutes)
            ids.append(str(alert.id))
        await session.commit()
    for alert_id in ids:
        process_alert.delay(alert_id)
    return len(ids)


async def _notify(snapshot: ResultSnapshot, alert: Alert) -> None:
    if not alert.user.telegram_chat_id:
        return
    itineraries = [
        NormalizedItinerary.model_validate(item)
        for item in snapshot.result_payload.get("itineraries", [])
    ]
    text, markup = render_snapshot_page(
        snapshot_id=snapshot.id,
        alert_id=alert.id,
        itineraries=itineraries,
        page=0,
        change_summary=snapshot.change_summary,
        observed_at=snapshot.created_at,
        source_status=snapshot.result_payload.get("source_status", {}),
    )
    message = await get_bot().send_message(
        chat_id=alert.user.telegram_chat_id,
        text=text,
        reply_markup=markup,
    )
    async with SessionFactory() as session:
        stored = await session.get(ResultSnapshot, snapshot.id)
        if stored:
            stored.telegram_chat_id = message.chat.id
            stored.telegram_message_id = message.message_id
            await session.commit()


async def _expire(alert: Alert) -> None:
    alert.status = AlertStatus.EXPIRED.value
    chat_id = alert.user.telegram_chat_id
    async with SessionFactory() as session:
        stored = await session.get(Alert, alert.id)
        if stored:
            stored.status = AlertStatus.EXPIRED.value
            await session.commit()
    if chat_id:
        try:
            await get_bot().send_message(
                chat_id,
                "The outbound time window has passed. Monitoring stopped automatically.",
            )
        except (TelegramAPIError, RuntimeError):
            pass


async def _load_alert(alert_id: uuid.UUID) -> Alert | None:
    async with SessionFactory() as session:
        return await session.scalar(
            select(Alert).options(selectinload(Alert.user)).where(Alert.id == alert_id)
        )


async def _process_alert(alert_id: str) -> None:
    parsed_id = uuid.UUID(alert_id)
    alert = await _load_alert(parsed_id)
    if not alert or alert.status != AlertStatus.ACTIVE.value:
        return
    if alert.expires_at <= utc_now():
        await _expire(alert)
        return
    criteria = AlertCriteria.model_validate(alert.criteria)
    batch = await ScraperManager(settings).search(criteria)

    async with SessionFactory() as session:
        alert = await session.scalar(
            select(Alert).options(selectinload(Alert.user)).where(Alert.id == parsed_id)
        )
        if not alert or alert.status != AlertStatus.ACTIVE.value:
            return
        previous = await session.scalar(
            select(ResultSnapshot)
            .where(ResultSnapshot.alert_id == alert.id)
            .order_by(ResultSnapshot.created_at.desc())
            .limit(1)
        )
        changes = await reconcile_offer_states(session, alert.id, batch)
        digest = snapshot_digest(batch)
        should_notify = previous is None or changes.has_changes or previous.digest != digest
        snapshot: ResultSnapshot | None = None
        if should_notify:
            snapshot = ResultSnapshot(
                alert_id=alert.id,
                digest=digest,
                result_payload=snapshot_payload(batch),
                change_summary=changes.as_dict(),
            )
            session.add(snapshot)

        for source, source_status in batch.source_status.items():
            session.add(
                ScrapeRun(
                    alert_id=alert.id,
                    source=source,
                    status="success" if source_status.get("ok") else "failed",
                    search_count=int(source_status.get("searches", 0)),
                    result_count=int(source_status.get("results", 0)),
                    error="; ".join(source_status.get("errors", []))[:2000] or None,
                    finished_at=utc_now(),
                )
            )
        alert.last_run_at = utc_now()
        alert.run_count += 1
        alert.next_run_at = next_run_time(alert, alert.last_run_at)
        await session.commit()
        snapshot_id = snapshot.id if snapshot else None

    if snapshot_id:
        snapshot_alert = await _load_alert(parsed_id)
        async with SessionFactory() as session:
            stored_snapshot = await session.get(ResultSnapshot, snapshot_id)
        if stored_snapshot and snapshot_alert:
            try:
                await _notify(stored_snapshot, snapshot_alert)
            except (TelegramAPIError, RuntimeError):
                # Results remain stored; a Telegram outage must not corrupt alert state.
                pass


@celery_app.task(name="app.worker.tasks.dispatch_due_alerts")
def dispatch_due_alerts() -> int:
    return asyncio.run(_dispatch_due_alerts())


@celery_app.task(
    name="app.worker.tasks.process_alert",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def process_alert(alert_id: str) -> None:
    asyncio.run(_process_alert(alert_id))

