from datetime import date, time

import pytest
from pydantic import ValidationError

from app.core.dates import gregorian_to_jalali, jalali_date_string
from app.domain.types import AlertCriteria, DateWindow, PassengerCounts, TimeWindow


def test_gregorian_to_jalali() -> None:
    assert gregorian_to_jalali(date(2026, 8, 11)) == (1405, 5, 20)
    assert jalali_date_string(date(2026, 3, 21)) == "1405-01-01"


def test_seven_day_range_is_allowed() -> None:
    assert DateWindow(start=date(2026, 8, 11), end=date(2026, 8, 17))


def test_eight_day_range_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DateWindow(start=date(2026, 8, 11), end=date(2026, 8, 18))


def test_infants_require_adults() -> None:
    with pytest.raises(ValidationError):
        PassengerCounts(adults=1, infants=2)


def test_round_trip_rejects_return_range_entirely_before_outbound() -> None:
    with pytest.raises(ValidationError):
        AlertCriteria(
            trip_type="round_trip",
            origin="THR",
            destination="MHD",
            outbound_dates={"start": "2026-08-11", "end": "2026-08-13"},
            outbound_times={"start": "17:00", "end": "23:00"},
            return_dates={"start": "2026-08-09", "end": "2026-08-10"},
            return_times={"start": "08:00", "end": "12:00"},
        )


def test_round_trip_allows_overlapping_flexible_ranges() -> None:
    criteria = AlertCriteria(
        trip_type="round_trip",
        origin="THR",
        destination="MHD",
        outbound_dates={"start": "2026-08-11", "end": "2026-08-13"},
        outbound_times={"start": "17:00", "end": "23:00"},
        return_dates={"start": "2026-08-12", "end": "2026-08-15"},
        return_times={"start": "08:00", "end": "12:00"},
    )
    assert criteria.return_dates is not None


def test_overnight_time_window_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TimeWindow(start=time(23), end=time(2))
