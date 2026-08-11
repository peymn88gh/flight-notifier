from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.domain.types import AlertCriteria, AlertStatus


class SessionResponse(BaseModel):
    user_id: uuid.UUID
    phone_masked: str
    first_name: str | None


class AlertCreate(BaseModel):
    criteria: AlertCriteria


class AlertResponse(BaseModel):
    id: uuid.UUID
    status: AlertStatus
    criteria: AlertCriteria
    expires_at: datetime
    next_run_at: datetime
    created_at: datetime


class LocationResponse(BaseModel):
    code: str
    city_fa: str
    city_en: str
    airport_fa: str
    airport_en: str
    aliases: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str = "ok"

