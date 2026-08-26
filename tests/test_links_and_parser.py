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


def _dom_parser() -> GenericFlightParser:
    search_url = build_search_url(SourceName.TRIP, criteria(), date(2026, 8, 30), None)
    return GenericFlightParser(
        SourceName.TRIP,
        criteria(),
        date(2026, 8, 30),
        None,
        search_url,
        datetime(2026, 8, 11, tzinfo=UTC),
    )


def test_dom_cards_without_a_specific_link_collapse_to_one() -> None:
    parser = _dom_parser()
    cards = [
        {"text": "Mahan Air\n14:30\n1,500,000 تومان", "url": None, "has_specific_link": False},
        {"text": "Iran Air\n18:45\n2,000,000 تومان", "url": None, "has_specific_link": False},
    ]
    results = parser.parse_dom_cards(cards)
    assert len(results) == 1
    assert results[0].outbound.airline == "Mahan Air"
    assert results[0].offers[0].amount_toman == 1_500_000
    assert str(results[0].offers[0].booking_url) == parser.search_url


def test_dom_cards_with_specific_links_are_not_collapsed() -> None:
    parser = _dom_parser()
    cards = [
        {
            "text": "Mahan Air\n14:30\n1,500,000 تومان",
            "url": "https://trip.ir/flight/booking/detail/1",
            "has_specific_link": True,
        },
        {
            "text": "Iran Air\n18:45\n2,000,000 تومان",
            "url": "https://trip.ir/flight/booking/detail/2",
            "has_specific_link": True,
        },
    ]
    results = parser.parse_dom_cards(cards)
    assert len(results) == 2
    urls = {str(item.offers[0].booking_url) for item in results}
    assert urls == {
        "https://trip.ir/flight/booking/detail/1",
        "https://trip.ir/flight/booking/detail/2",
    }


def test_dom_cards_exact_duplicates_from_overlapping_selectors_merge() -> None:
    parser = _dom_parser()
    duplicate_text = "Mahan Air\n14:30\n1,500,000 تومان"
    cards = [
        {"text": duplicate_text, "url": None, "has_specific_link": False},
        {"text": duplicate_text, "url": None, "has_specific_link": False},
    ]
    results = parser.parse_dom_cards(cards)
    assert len(results) == 1
    assert len(results[0].offers) == 1


def test_dom_card_with_zero_remaining_seats_is_excluded() -> None:
    parser = _dom_parser()
    cards = [
        {
            "text": "Mahan Air\n14:30\nظرفیت باقیمانده: ۰\n1,500,000 تومان",
            "url": None,
            "has_specific_link": False,
        }
    ]
    assert parser.parse_dom_cards(cards) == []


def test_payload_status_text_for_sold_out_ticket_is_excluded() -> None:
    search_url = build_search_url(SourceName.TRIP, criteria(), date(2026, 8, 30), None)
    parser = GenericFlightParser(
        SourceName.TRIP,
        criteria(),
        date(2026, 8, 30),
        None,
        search_url,
        datetime(2026, 8, 11, tzinfo=UTC),
    )
    payload = {
        "departureDateTime": "2026-08-30T18:20:00+03:30",
        "airlineName": "Mahan Air",
        "flightNumber": "W51020",
        "price": 12_500_000,
        "statusText": "بلیط موجود نیست",
    }
    assert parser.parse_payloads([payload]) == []

