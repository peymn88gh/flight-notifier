from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.bot.runtime import get_bot
from app.core.config import get_settings
from app.db.base import create_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not settings.is_production:
        await create_schema()
    if settings.telegram_bot_token and settings.base_url.startswith("https://"):
        webhook_url = (
            f"{settings.base_url.rstrip('/')}/telegram/webhook/"
            f"{settings.telegram_webhook_secret}"
        )
        await get_bot().set_webhook(
            webhook_url,
            secret_token=settings.telegram_webhook_secret,
            allowed_updates=["message", "callback_query"],
        )
        logger.info("Telegram webhook configured")
    yield
    if settings.telegram_bot_token:
        await get_bot().session.close()


app = FastAPI(
    title="Flight Notifier",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)
app.include_router(router)

frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/app", StaticFiles(directory=frontend_dist, html=True), name="mini-app")


@app.get("/", include_in_schema=False)
async def index() -> dict[str, str]:
    return {"service": "flight-notifier", "status": "ok"}

