from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Alert, ResultSnapshot, User, utc_now
from app.domain.types import AlertCriteria, AlertKind, AlertStatus, HotelCriteria


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def by_phone(self, phone_e164: str) -> User | None:
        return await self.session.scalar(select(User).where(User.phone_e164 == phone_e164))

    async def by_telegram_id(self, telegram_user_id: int) -> User | None:
        return await self.session.scalar(
            select(User).where(User.telegram_user_id == telegram_user_id)
        )

    async def bind_contact(
        self,
        *,
        phone_e164: str,
        telegram_user_id: int,
        telegram_chat_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
    ) -> User:
        user = await self.by_phone(phone_e164)
        if not user or not user.is_allowed:
            raise PermissionError("This phone number is not authorized")
        if user.telegram_user_id not in (None, telegram_user_id):
            raise PermissionError("This phone number is already bound to another Telegram account")

        existing = await self.by_telegram_id(telegram_user_id)
        if existing and existing.id != user.id:
            raise PermissionError("This Telegram account is already bound to another phone number")

        now = utc_now()
        user.telegram_user_id = telegram_user_id
        user.telegram_chat_id = telegram_chat_id
        user.telegram_username = username
        user.first_name = first_name
        user.last_name = last_name
        user.bound_at = user.bound_at or now
        user.last_seen_at = now
        await self.session.commit()
        return user


class AlertRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def lock_user(self, user_id: uuid.UUID) -> None:
        await self.session.execute(
            select(User.id).where(User.id == user_id).with_for_update()
        )

    async def create(
        self,
        user: User,
        criteria: AlertCriteria | HotelCriteria,
        expires_at: datetime,
        kind: AlertKind = AlertKind.FLIGHT,
    ) -> Alert:
        now = utc_now()
        alert = Alert(
            user_id=user.id,
            kind=kind.value,
            status=AlertStatus.ACTIVE.value,
            criteria=criteria.model_dump(mode="json"),
            expires_at=expires_at,
            next_run_at=now,
        )
        self.session.add(alert)
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

    async def get_for_user(self, alert_id: uuid.UUID, user_id: uuid.UUID) -> Alert | None:
        return await self.session.scalar(
            select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id)
        )

    async def list_for_user(self, user_id: uuid.UUID, kind: AlertKind | None = None) -> list[Alert]:
        query = select(Alert).where(Alert.user_id == user_id)
        if kind is not None:
            query = query.where(Alert.kind == kind.value)
        rows = await self.session.scalars(query.order_by(Alert.created_at.desc()))
        return list(rows)

    async def active_count(self, user_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(Alert).where(
                    Alert.user_id == user_id, Alert.status == AlertStatus.ACTIVE.value
                )
            )
            or 0
        )

    async def created_today_count(self, user_id: uuid.UUID) -> int:
        since = datetime.now(UTC) - timedelta(days=1)
        return int(
            await self.session.scalar(
                select(func.count()).select_from(Alert).where(
                    Alert.user_id == user_id, Alert.created_at >= since
                )
            )
            or 0
        )

    async def cancel(self, alert: Alert) -> Alert:
        if alert.status == AlertStatus.ACTIVE.value:
            alert.status = AlertStatus.CANCELLED.value
            alert.cancelled_at = utc_now()
            await self.session.commit()
        return alert

    async def latest_snapshot(self, alert_id: uuid.UUID) -> ResultSnapshot | None:
        return await self.session.scalar(
            select(ResultSnapshot)
            .where(ResultSnapshot.alert_id == alert_id)
            .order_by(ResultSnapshot.created_at.desc())
            .limit(1)
        )

