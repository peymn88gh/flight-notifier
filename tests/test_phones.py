import pytest

from app.core.phones import normalize_iranian_phone, redact_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("09396451429", "+989396451429"),
        ("9396451429", "+989396451429"),
        ("989396451429", "+989396451429"),
        ("+98 939 645 1429", "+989396451429"),
    ],
)
def test_normalize_iranian_phone(raw: str, expected: str) -> None:
    assert normalize_iranian_phone(raw) == expected


@pytest.mark.parametrize("raw", ["123", "02112345678", "+12025550123"])
def test_rejects_non_mobile_numbers(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_iranian_phone(raw)


def test_redacts_phone() -> None:
    assert redact_phone("+989396451429") == "+989***429"

