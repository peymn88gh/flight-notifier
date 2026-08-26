from datetime import UTC, date, datetime
from urllib.parse import parse_qs, urlparse

from app.domain.types import HotelCriteria, HotelSourceName
from app.scrapers.hotel_links import (
    build_hotel_search_url,
    checkout_date,
    validate_hotel_source_url,
)
from app.scrapers.hotel_parser import GenericHotelParser


def criteria(destination: str = "IST", nights: int = 2) -> HotelCriteria:
    return HotelCriteria(
        destination=destination,
        checkin_dates={"start": "2026-09-10", "end": "2026-09-10"},
        nights=nights,
        rooms=1,
        occupancy={"adults": 2, "children": 0},
    )


def test_checkout_date_adds_nights() -> None:
    assert checkout_date(date(2026, 9, 10), 3) == date(2026, 9, 13)


def test_alibaba_hotel_link_uses_country_prefixed_slug() -> None:
    url = build_hotel_search_url(HotelSourceName.ALIBABA, criteria(), date(2026, 9, 10))
    assert url is not None
    assert urlparse(url).path == "/hotel/tr-istanbul"
    query = parse_qs(urlparse(url).query)
    assert query["checkin"] == ["2026-09-10"]
    assert query["checkout"] == ["2026-09-12"]
    assert query["adult"] == ["2"]


def test_unknown_destination_returns_none() -> None:
    url = build_hotel_search_url(HotelSourceName.ALIBABA, criteria("ZZZ"), date(2026, 9, 10))
    assert url is None


def test_hotel_source_link_validation_fails_closed() -> None:
    assert validate_hotel_source_url(HotelSourceName.TRIP, "https://trip.ir/hotel/istanbul")
    assert not validate_hotel_source_url(
        HotelSourceName.TRIP, "https://trip.ir.attacker.example/hotel"
    )
    assert not validate_hotel_source_url(HotelSourceName.TRIP, "http://trip.ir/hotel/istanbul")


def _parser(destination: str = "IST") -> GenericHotelParser:
    search_url = build_hotel_search_url(
        HotelSourceName.TRIP, criteria(destination), date(2026, 9, 10)
    )
    assert search_url is not None
    return GenericHotelParser(
        HotelSourceName.TRIP,
        criteria(destination),
        date(2026, 9, 10),
        search_url,
        datetime(2026, 8, 11, tzinfo=UTC),
    )


def test_parser_emits_hotel_and_converts_rials() -> None:
    parser = _parser()
    payload = {
        "hotelName": "Grand Bosphorus Hotel",
        "stars": 4,
        "totalPrice": 45_000_000,
        "currency": "IRR",
        "address": "Taksim, Istanbul",
        "bookingUrl": "https://trip.ir/hotel/detail/123",
    }
    results = parser.parse_payloads([payload])
    assert len(results) == 1
    assert results[0].hotel_name == "Grand Bosphorus Hotel"
    assert results[0].star_rating == 4
    assert results[0].offers[0].amount_toman == 4_500_000


def test_parser_rejects_candidate_without_price() -> None:
    parser = _parser()
    payload = {"hotelName": "No Price Hotel", "stars": 3, "address": "Somewhere"}
    assert parser.parse_payloads([payload]) == []


def test_parser_excludes_sold_out_hotel() -> None:
    parser = _parser()
    payload = {
        "hotelName": "Fully Booked Hotel",
        "totalPrice": 10_000_000,
        "statusText": "ظرفیت تکمیل است",
        "bookingUrl": "https://trip.ir/hotel/detail/999",
    }
    assert parser.parse_payloads([payload]) == []


def test_dom_cards_without_specific_link_collapse_to_cheapest() -> None:
    parser = _parser()
    cards = [
        {"text": "Hotel A\n3,000,000 تومان", "url": None, "has_specific_link": False},
        {"text": "Hotel B\n2,200,000 تومان", "url": None, "has_specific_link": False},
    ]
    results = parser.parse_dom_cards(cards)
    assert len(results) == 1
    assert results[0].hotel_name == "Hotel B"
    assert results[0].offers[0].amount_toman == 2_200_000
