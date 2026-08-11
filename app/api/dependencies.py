from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import TelegramAuthError, validate_telegram_init_data
from app.db.base import get_session
from app.db.models import User
from app.db.repositories import UserRepository

DbSession = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


async def get_current_user(
    session: DbSession,
    settings: AppSettings,
    telegram_init_data: Annotated[str | None, Header(alias="X-Telegram-Init-Data")] = None,
) -> User:
    try:
        identity = validate_telegram_init_data(
            telegram_init_data or "",
            settings.telegram_bot_token,
            max_age_seconds=settings.telegram_init_data_max_age_seconds,
        )
    except TelegramAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await UserRepository(session).by_telegram_id(identity.user_id)
    if not user or not user.is_allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Share an authorized phone number with the bot before opening the app",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]

