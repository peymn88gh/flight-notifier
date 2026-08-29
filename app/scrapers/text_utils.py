from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Any

DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

UNAVAILABLE_STATUS_TERMS = (
    "تکمیلظرفیت",
    "ظرفیتتکمیل",
    "ظرفیتتکمیلاست",
    "ظرفیتپروازتکمیل",
    "کنسلشده",
    "لغوشده",
    "پروازلغوشد",
    "پروازکنسلشد",
    "پروازکنسل",
    "ناموجود",
    "غیرفعال",
    "غیرقابلرزرو",
    "غیرقابلخرید",
    "امکانرزروجودندارد",
    "امکانخریدوجودندارد",
    "بلیطموجودنیست",
    "بلیطیموجودنیست",
    "فروختهشد",
    "بهفروشنمیرسد",
    "پروازپرشد",
    "صندلیخالینیست",
    "اتاقموجودنیست",
    "اتاقیموجودنیست",
    "ظرفیتهتلتکمیل",
    "رزروتکمیل",
    "soldout",
    "notavailable",
    "unavailable",
    "cancelled",
    "canceled",
    "flightfull",
    "fullybooked",
    "noroomsavailable",
)


def key_map(value: dict[str, Any]) -> dict[str, Any]:
    return {re.sub(r"[^a-z0-9]", "", str(key).lower()): item for key, item in value.items()}


def first(mapping: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        normalized = re.sub(r"[^a-z0-9]", "", name.lower())
        if normalized in mapping and mapping[normalized] not in (None, ""):
            return mapping[normalized]
    return None


def text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        mapped = key_map(value)
        # "fa"/"en" last: several of these sites (confirmed: Alibaba) shape bilingual
        # fields as {"fa": "...", "en": "..."} rather than a name/title/code key.
        value = first(mapped, ["name", "displayName", "title", "code", "fa", "en"])
    if value is None:
        return None
    return str(value).strip() or None


def decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    raw = str(value).translate(DIGIT_TRANSLATION)
    raw = re.sub(r"[^0-9.]", "", raw)
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def normalized_status(value: Any) -> str:
    return re.sub(
        r"[\s_\-‌‏]+",
        "",
        str(value or "").translate(DIGIT_TRANSLATION).casefold(),
    )


def contains_unavailable_status(value: Any) -> bool:
    normalized = normalized_status(value)
    return any(term in normalized for term in UNAVAILABLE_STATUS_TERMS)


def flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = normalized_status(value)
    if normalized in {"true", "1", "yes", "بله"}:
        return True
    if normalized in {"false", "0", "no", "خیر"}:
        return False
    return None
