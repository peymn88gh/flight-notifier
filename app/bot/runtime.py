from __future__ import annotations

import logging
import uuid

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)
from sqlalchemy import select

from app.bot.formatting import render_snapshot_page
from app.core.config import get_settings
from app.core.phones import normalize_iranian_phone
from app.db.base import SessionFactory
from app.db.models import Alert, ResultSnapshot, User
from app.db.repositories import AlertRepository, UserRepository
from app.domain.types import NormalizedItinerary

logger = logging.getLogger(__name__)
settings = get_settings()
_bot: Bot | None = None
_dispatcher: Dispatcher | None = None
router = Router(name="flight-notifier")


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        if not settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        _bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    return _bot


def get_dispatcher() -> Dispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(router)
    return _dispatcher


def _contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="اشتراک شماره تلفن", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="برای ورود، شماره حساب تلگرام را به اشتراک بگذارید",
    )


def _app_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="باز کردن فرم جستجوی پرواز",
                    web_app=WebAppInfo(url=f"{settings.base_url.rstrip('/')}/app/"),
                )
            ]
        ]
    )


@router.message(CommandStart())
async def start(message: Message) -> None:
    if not message.from_user:
        return
    async with SessionFactory() as session:
        user = await UserRepository(session).by_telegram_id(message.from_user.id)
    if user and user.is_allowed:
        await message.answer(
            "خوش آمدید. برای ساخت یا مدیریت پایش پرواز، فرم را باز کنید.",
            reply_markup=_app_keyboard(),
        )
        return
    await message.answer(
        "برای بررسی دسترسی، شماره تلفن متصل به همین حساب تلگرام را به اشتراک بگذارید.",
        reply_markup=_contact_keyboard(),
    )


@router.message(F.contact)
async def receive_contact(message: Message) -> None:
    if not message.from_user or not message.contact:
        return
    if message.contact.user_id != message.from_user.id:
        await message.answer("فقط شماره متعلق به همین حساب تلگرام پذیرفته می‌شود.")
        return
    try:
        phone = normalize_iranian_phone(message.contact.phone_number)
        async with SessionFactory() as session:
            await UserRepository(session).bind_contact(
                phone_e164=phone,
                telegram_user_id=message.from_user.id,
                telegram_chat_id=message.chat.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
    except (ValueError, PermissionError) as exc:
        await message.answer(
            f"دسترسی تأیید نشد: {exc}",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    await message.answer("دسترسی شما تأیید شد.", reply_markup=ReplyKeyboardRemove())
    await message.answer("فرم جستجوی پرواز آماده است.", reply_markup=_app_keyboard())


@router.message(Command("alerts"))
async def alerts(message: Message) -> None:
    if not message.from_user:
        return
    async with SessionFactory() as session:
        user = await UserRepository(session).by_telegram_id(message.from_user.id)
        if not user or not user.is_allowed:
            await message.answer("ابتدا با دستور /start شماره خود را تأیید کنید.")
            return
        values = await AlertRepository(session).list_for_user(user.id)
    active = sum(1 for item in values if item.status == "active")
    await message.answer(
        f"تعداد پایش‌های فعال: {active}",
        reply_markup=_app_keyboard(),
    )


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data.startswith("pg:"))
async def paginate(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        return
    try:
        _, snapshot_text, page_text = callback.data.split(":", 2)
        snapshot_id = uuid.UUID(snapshot_text)
        page = int(page_text)
    except (ValueError, TypeError):
        await callback.answer("صفحه نامعتبر است", show_alert=True)
        return

    async with SessionFactory() as session:
        row = await session.execute(
            select(ResultSnapshot, Alert, User)
            .join(Alert, ResultSnapshot.alert_id == Alert.id)
            .join(User, Alert.user_id == User.id)
            .where(ResultSnapshot.id == snapshot_id)
        )
        record = row.first()
        if not record:
            await callback.answer("Result unavailable", show_alert=True)
            return
        snapshot, alert, record_user = record
        if record_user.telegram_user_id != callback.from_user.id:
            await callback.answer("این نتیجه در دسترس نیست", show_alert=True)
            return
        itineraries = [
            NormalizedItinerary.model_validate(item)
            for item in snapshot.result_payload.get("itineraries", [])
        ]
        text, markup = render_snapshot_page(
            snapshot_id=snapshot.id,
            alert_id=alert.id,
            itineraries=itineraries,
            page=page,
            change_summary=snapshot.change_summary,
            observed_at=snapshot.created_at,
            source_status=snapshot.result_payload.get("source_status", {}),
        )
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cx:"))
async def cancel(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    try:
        alert_id = uuid.UUID(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("شناسه پایش نامعتبر است", show_alert=True)
        return
    async with SessionFactory() as session:
        user = await UserRepository(session).by_telegram_id(callback.from_user.id)
        if not user:
            await callback.answer("دسترسی نامعتبر است", show_alert=True)
            return
        repository = AlertRepository(session)
        alert = await repository.get_for_user(alert_id, user.id)
        if not alert:
            await callback.answer("پایش پیدا نشد", show_alert=True)
            return
        await repository.cancel(alert)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer("پایش لغو شد", show_alert=True)
