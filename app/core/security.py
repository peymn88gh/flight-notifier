from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl


class TelegramAuthError(ValueError):
    pass


@dataclass(frozen=True)
class TelegramIdentity:
    user_id: int
    first_name: str
    last_name: str | None
    username: str | None
    language_code: str | None
    auth_date: int


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 3600,
    now: int | None = None,
) -> TelegramIdentity:
    if not init_data or not bot_token:
        raise TelegramAuthError("Telegram authentication data is missing")

    values = dict(parse_qsl(init_data, keep_blank_values=True))
    supplied_hash = values.pop("hash", None)
    if not supplied_hash:
        raise TelegramAuthError("Telegram authentication hash is missing")

    data_check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, supplied_hash):
        raise TelegramAuthError("Telegram authentication signature is invalid")

    try:
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise TelegramAuthError("Telegram authentication payload is malformed") from exc

    current_time = int(time.time()) if now is None else now
    if auth_date > current_time + 30 or current_time - auth_date > max_age_seconds:
        raise TelegramAuthError("Telegram authentication data has expired")

    return TelegramIdentity(
        user_id=user_id,
        first_name=str(user.get("first_name", "")),
        last_name=user.get("last_name"),
        username=user.get("username"),
        language_code=user.get("language_code"),
        auth_date=auth_date,
    )

