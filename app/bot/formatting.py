from __future__ import annotations

import html
import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.domain.types import NormalizedItinerary, PriceKind

SOURCE_LABELS = {
    "alibaba": "علی‌بابا",
    "flightio": "فلایتیو",
    "trip": "تریپ",
    "respina24": "رسپینا۲۴",
}


def _money(value: Decimal | None) -> str:
    if value is None:
        return "قیمت در سایت"
    return f"{value:,.0f} تومان"


def _leg_text(label: str, leg) -> str:
    departure = leg.departure.astimezone(ZoneInfo("Asia/Tehran"))
    arrival = leg.arrival.astimezone(ZoneInfo("Asia/Tehran")) if leg.arrival else None
    arrival_text = f" ← {arrival:%H:%M}" if arrival else ""
    flight = f" · {html.escape(leg.flight_number)}" if leg.flight_number else ""
    return (
        f"<b>{label}</b>  {html.escape(leg.origin)} ← {html.escape(leg.destination)}\n"
        f"{departure:%Y-%m-%d} · {departure:%H:%M}{arrival_text}\n"
        f"{html.escape(leg.airline)}{flight}"
    )


def render_snapshot_page(
    *,
    snapshot_id: uuid.UUID,
    alert_id: uuid.UUID,
    itineraries: list[NormalizedItinerary],
    page: int,
    change_summary: dict | None = None,
    observed_at: datetime | None = None,
    source_status: dict | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    total = len(itineraries)
    if total == 0 and source_status and all(
        not value.get("ok", False) for value in source_status.values()
    ):
        text = (
            "<b>Search temporarily delayed</b>\\n"
            "Monitoring remains active and the service will retry automatically."
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Cancel alert", callback_data=f"cx:{alert_id}")]
            ]
        )
        return text, keyboard
    if total == 0:
        text = (
            "🔎 <b>فعلاً پرواز مطابق شرایط پیدا نشد</b>\n"
            "پایش فعال است و در صورت پیدا شدن نتیجه اطلاع می‌دهم."
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="لغو پایش", callback_data=f"cx:{alert_id}")]
            ]
        )
        return text, keyboard

    page = max(0, min(page, total - 1))
    itinerary = itineraries[page]
    sections = [f"✈️ <b>نتایج پرواز</b> · {page + 1} از {total}"]
    if change_summary:
        added = int(change_summary.get("added", 0))
        changed = int(change_summary.get("changed", 0))
        removed = int(change_summary.get("removed", 0))
        if added or changed or removed:
            sections.append(f"تغییرات: {added}+ جدید · {changed} تغییر قیمت · {removed} حذف")
    sections.append(_leg_text("رفت", itinerary.outbound))
    if itinerary.return_leg:
        sections.append(_leg_text("برگشت", itinerary.return_leg))

    offer_lines: list[str] = []
    link_buttons: list[list[InlineKeyboardButton]] = []
    for offer in sorted(
        itinerary.offers,
        key=lambda item: (item.amount_toman is None, item.amount_toman or Decimal("0")),
    ):
        source = SOURCE_LABELS.get(offer.source.value, offer.source.value)
        qualifier = {
            PriceKind.TOTAL: "کل مسافران",
            PriceKind.PER_ADULT: "هر بزرگسال",
            PriceKind.FROM: "از",
        }[offer.price_kind]
        offer_lines.append(f"• <b>{source}</b>: {_money(offer.amount_toman)} · {qualifier}")
        link_buttons.append(
            [InlineKeyboardButton(text=f"باز کردن در {source}", url=str(offer.booking_url))]
        )
    sections.append("\n".join(offer_lines))
    if observed_at:
        seen = observed_at.astimezone(ZoneInfo("Asia/Tehran"))
        sections.append(f"<i>آخرین بررسی: {seen:%Y-%m-%d %H:%M} — قیمت در سایت تأیید شود.</i>")

    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(text="قبلی", callback_data=f"pg:{snapshot_id}:{page - 1}")
        )
    navigation.append(InlineKeyboardButton(text=f"{page + 1}/{total}", callback_data="noop"))
    if page < total - 1:
        navigation.append(
            InlineKeyboardButton(text="بعدی", callback_data=f"pg:{snapshot_id}:{page + 1}")
        )
    rows = link_buttons + [navigation]
    rows.append([InlineKeyboardButton(text="لغو پایش", callback_data=f"cx:{alert_id}")])
    return "\n\n".join(sections), InlineKeyboardMarkup(inline_keyboard=rows)
