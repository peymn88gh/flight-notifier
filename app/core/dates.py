from __future__ import annotations

from datetime import date, timedelta


def gregorian_to_jalali(value: date) -> tuple[int, int, int]:
    """Convert a Gregorian date to Jalali without a runtime locale dependency."""
    gy, gm, gd = value.year, value.month, value.day
    gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        355666
        + 365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        + gd
        + gdm[gm - 1]
    )
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def jalali_date_string(value: date) -> str:
    year, month, day = gregorian_to_jalali(value)
    return f"{year:04d}-{month:02d}-{day:02d}"


def iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)

