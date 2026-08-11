from __future__ import annotations

import re

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_iranian_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value.translate(PERSIAN_DIGITS))
    if digits.startswith("0098"):
        digits = digits[2:]
    if digits.startswith("98") and len(digits) == 12:
        national = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        national = digits[1:]
    elif len(digits) == 10:
        national = digits
    else:
        raise ValueError("Enter a valid Iranian mobile number")

    if not national.startswith("9"):
        raise ValueError("Iranian mobile numbers must start with 09")
    return f"+98{national}"


def redact_phone(phone_e164: str) -> str:
    if len(phone_e164) < 7:
        return "***"
    return f"{phone_e164[:4]}***{phone_e164[-3:]}"

