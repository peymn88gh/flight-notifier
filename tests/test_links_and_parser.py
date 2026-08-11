from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

from app.core.dates import jalali_date_string
from app.domain.types import AlertCriteria, SourceName
from app.scrapers.links import build_search_url, validate_source_url
from app.scrapers.parser import GenericFlightParser


def criteria(round_trip: bool = False) -> AlertCriteria:
    return AlertCriteria(
        trip_type="round_trip" if round_trip else "one_way",
        origin="THR",
        destination="MHD",
        outbound_dates={"start": "2026-08-30", "end": "2026-08-30"},
        outbound_times={"start": "17:00", "end": "23:00"},
        return_dates={"start": "2026-09-02", "end": "2026-09-02"} if round_trip else None,
        return_times={"start": "08:00", "end": "14:00"} if round_trip else None,
        passengers={"adults": 2, "children": 1, "infants": 0},
        cabin="economy",
    )


def test_alibaba_link_uses_jalali_and_party() -> None:
    going = date(2026, 8, 30)
    url = build_search_url(SourceName.ALIBABA, criteria(), going, None)
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).path == "/flights/THR-MHD"
    assert query["departing"] == [jalali_date_string(going)]
    assert query["adult"] == ["2"]
    assert query["child"] == ["1"]


def test_trip_link_uses_current_public_parameter_shape() -> None:
    url = build_search_url(
        SourceName.TRIP,
        criteria(round_trip=True),
        date(2026, 8, 30),
        date(2026, 9, 2),
    )
    query = parse_qs(urlparse(url).query)
    assert query["origin"] == ["THR"]
    assert query["destination"] == ["MHD"]
    assert query["outbound"] == ["2026-08-30"]
    assert query["inbound"] == ["2026-09-02"]
    assert query["adults"] == ["2"]


def test_source_link_validation_fails_closed() -> None:
    assert validate_source_url(SourceName.TRIP, "https://trip.ir/flight/THR-MHD")
    assert not validate_source_url(SourceName.TRIP, "https://trip.ir.attacker.example/offer")
    assert not validate_source_url(SourceName.TRIP, "http://trip.ir/offer")


def test_parser_emits_complete_round_trip_and_converts_rials() -> None:
    search_url = build_search_url(
        SourceName.TRIP,
        criteria(round_trip=True),
        date(2026, 8, 30),
        date(2026, 9, 2),
    )
    parser = GenericFlightParser(
        SourceName.TRIP,
        criteria(round_trip=True),
        date(2026, 8, 30),
        date(2026, 9, 2),
        search_url,
        datetime(2026, 8, 11, tzinfo=UTC),
    )
    payload = {
        "outbound": {
            "originIata": "THR",
            "destinationIata": "MHD",
            "departureDateTime": "2026-08-30T18:20:00+03:30",
            "arrivalDateTime": "2026-08-30T19:45:00+03:30",
            "airlineName": "Mahan Air",
            "flightNumber": "W51020",
        },
        "inbound": {
            "originIata": "MHD",
            "destinationIata": "THR",
            "departureDateTime": "2026-09-02T09:15:00+03:30",
            "arrivalDateTime": "2026-09-02T10:40:00+03:30",
            "airlineName": "Mahan Air",
            "flightNumber": "W51021",
        },
        "totalPrice": 125_000_000,
        "currency": "IRR",
        "bookingUrl": search_url,
    }
    values = parser.parse_payloads([payload])
    assert len(values) == 1
    assert values[0].return_leg is not None
    assert values[0].offers[0].amount_toman == 12_500_000


def test_parser_rejects_incomplete_round_trip() -> None:
    search_url = build_search_url(
        SourceName.TRIP,
        criteria(round_trip=True),
        date(2026, 8, 30),
        date(2026, 9, 2),
    )
    parser = GenericFlightParser(
        SourceName.TRIP,
        criteria(round_trip=True),
        date(2026, 8, 30),
        date(2026, 9, 2),
        search_url,
        datetime.now(UTC),
    )
    payload = {
        "departureDateTime": "2026-08-30T18:20:00+03:30",
        "airlineName": "Mahan Air",
        "flightNumber": "W51020",
        "price": 12_500_000,
    }
    assert parser.parse_payloads([payload]) == []

