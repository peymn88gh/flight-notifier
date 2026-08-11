import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.core.security import TelegramAuthError, validate_telegram_init_data


def make_init_data(token: str, now: int, user_id: int = 42) -> str:
    values = {
        "auth_date": str(now),
        "query_id": "test-query",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_validates_telegram_init_data() -> None:
    token = "123:secret"
    payload = make_init_data(token, 1_800_000_000)
    identity = validate_telegram_init_data(payload, token, now=1_800_000_010)
    assert identity.user_id == 42


def test_rejects_forged_and_expired_data() -> None:
    token = "123:secret"
    payload = make_init_data(token, 1_800_000_000)
    with pytest.raises(TelegramAuthError):
        validate_telegram_init_data(payload, "different", now=1_800_000_010)
    with pytest.raises(TelegramAuthError):
        validate_telegram_init_data(payload, token, max_age_seconds=60, now=1_800_001_000)

