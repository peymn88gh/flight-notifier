from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, status

from app.api.dependencies import AppSettings, CurrentUser, DbSession
from app.api.schemas import (
    AlertCreate,
    AlertResponse,
    HealthResponse,
    LocationResponse,
    SessionResponse,
)
from app.bot.runtime import get_bot, get_dispatcher
from app.core.phones import redact_phone
from app.db.repositories import AlertRepository
from app.domain.types import AlertCriteria, AlertStatus
from app.services.queue import enqueue_alert

router = APIRouter()


def _alert_response(alert) -> AlertResponse:
    return AlertResponse(
        id=alert.id,
        status=AlertStatus(alert.status),
        criteria=AlertCriteria.model_validate(alert.criteria),
        expires_at=alert.expires_at,
        next_run_at=alert.next_run_at,
        created_at=alert.created_at,
        last_run_at=alert.last_run_at,
        run_count=alert.run_count,
    )


def _expires_at(criteria: AlertCriteria) -> datetime:
    local = datetime.combine(
        criteria.outbound_dates.end,
        criteria.outbound_times.end,
        tzinfo=ZoneInfo(criteria.timezone),
    )
    return local.astimezone(UTC)


@router.get("/health", response_model=HealthResponse, tags=["operations"])
async def health() -> HealthResponse:
    return HealthResponse()


@router.post("/api/session", response_model=SessionResponse, tags=["authentication"])
async def create_session(user: CurrentUser, settings: AppSettings) -> SessionResponse:
    return SessionResponse(
        user_id=user.id,
        phone_masked=redact_phone(user.phone_e164),
        first_name=user.first_name,
        max_active_alerts=settings.max_active_alerts_per_user,
    )


@router.get("/api/locations", response_model=list[LocationResponse], tags=["alerts"])
async def locations(q: str = "") -> list[LocationResponse]:
    path = Path(__file__).resolve().parent.parent / "data" / "airports.json"
    values = json.loads(path.read_text(encoding="utf-8"))
    needle = q.strip().casefold()
    if needle:
        values = [
            item
            for item in values
            if needle
            in " ".join(
                [
                    item["code"],
                    item["city_fa"],
                    item["city_en"],
                    item["airport_fa"],
                    item["airport_en"],
                    *item.get("aliases", []),
                ]
            ).casefold()
        ]
    return [LocationResponse.model_validate(item) for item in values[:30]]


@router.post(
    "/api/alerts",
    response_model=AlertResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["alerts"],
)
async def create_alert(
    payload: AlertCreate,
    user: CurrentUser,
    session: DbSession,
    settings: AppSettings,
) -> AlertResponse:
    criteria = payload.criteria
    now_local = datetime.now(ZoneInfo(criteria.timezone))
    if criteria.outbound_dates.start < now_local.date():
        raise HTTPException(status_code=422, detail="Outbound date range cannot be in the past")

    repository = AlertRepository(session)
    await repository.lock_user(user.id)
    if await repository.active_count(user.id) >= settings.max_active_alerts_per_user:
        raise HTTPException(
            status_code=429,
            detail=(
                f"حداکثر {settings.max_active_alerts_per_user} پایش فعال مجاز است. "
                "برای ادامه یکی را حذف کنید."
            ),
        )
    if await repository.created_today_count(user.id) >= settings.max_alerts_per_day:
        raise HTTPException(status_code=429, detail="Daily alert limit reached")

    alert = await repository.create(user, criteria, _expires_at(criteria))
    enqueue_alert(str(alert.id))
    return _alert_response(alert)


@router.get("/api/alerts", response_model=list[AlertResponse], tags=["alerts"])
async def list_alerts(user: CurrentUser, session: DbSession) -> list[AlertResponse]:
    alerts = await AlertRepository(session).list_for_user(user.id)
    return [_alert_response(alert) for alert in alerts]


@router.post("/api/alerts/{alert_id}/cancel", response_model=AlertResponse, tags=["alerts"])
async def cancel_alert(
    alert_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> AlertResponse:
    repository = AlertRepository(session)
    alert = await repository.get_for_user(alert_id, user.id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await repository.cancel(alert)
    return _alert_response(alert)


@router.post("/telegram/webhook/{path_secret}", include_in_schema=False)
async def telegram_webhook(
    path_secret: str,
    request: Request,
    settings: AppSettings,
) -> dict[str, bool]:
    if path_secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=404, detail="Not found")
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if header_secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret")
    update = Update.model_validate(await request.json(), context={"bot": get_bot()})
    await get_dispatcher().feed_update(get_bot(), update)
    return {"ok": True}
