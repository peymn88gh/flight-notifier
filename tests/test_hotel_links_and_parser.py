from datetime import UTC, date, datetime
from decimal import Decimal
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
    assert query["departing"] == ["2026-09-10"]
    assert query["returning"] == ["2026-09-12"]


def test_trip_hotel_link_is_plain_landing_page() -> None:
    url = build_hotel_search_url(HotelSourceName.TRIP, criteria(), date(2026, 9, 10))
    assert url == "https://www.trip.ir/hotel/istanbul"


def test_snapptrip_hotel_link_uses_city_country_slug_and_date_params() -> None:
    url = build_hotel_search_url(HotelSourceName.SNAPPTRIP, criteria(), date(2026, 9, 10))
    assert url is not None
    assert urlparse(url).path == "/international-hotel/istanbul-tr"
    query = parse_qs(urlparse(url).query)
    assert query["date_from"] == ["2026-09-10"]
    assert query["date_to"] == ["2026-09-12"]
    assert query["occupants"] == ["2"]


def test_snapptrip_returns_none_for_unverified_domestic_slug() -> None:
    url = build_hotel_search_url(HotelSourceName.SNAPPTRIP, criteria("MHD"), date(2026, 9, 10))
    assert url is None


def test_respina24_domestic_uses_hotel_path() -> None:
    url = build_hotel_search_url(HotelSourceName.RESPINA24, criteria("MHD"), date(2026, 9, 10))
    assert url is not None
    assert urlparse(url).path == "/hotel/mashhad"
    query = parse_qs(urlparse(url).query)
    assert query["departing"] == ["2026-09-10"]
    assert query["returning"] == ["2026-09-12"]


def test_respina24_international_uses_search_path_with_nationality() -> None:
    url = build_hotel_search_url(HotelSourceName.RESPINA24, criteria("IST"), date(2026, 9, 10))
    assert url is not None
    assert urlparse(url).path == "/internationalhotel/search/Turkey/Istanbul"
    query = parse_qs(urlparse(url).query)
    assert query["checkin"] == ["2026-09-10"]
    assert query["checkout"] == ["2026-09-12"]
    assert query["nationality"] == ["IR"]


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


def test_parser_extracts_name_from_bilingual_fa_en_object() -> None:
    """Confirmed live against Alibaba on 2026-08-29: its hotel objects shape name and
    address as {"fa": "...", "en": "..."} rather than a name/title/code key, and the
    candidate was being silently dropped because hotel_name came back None.
    """
    search_url = build_hotel_search_url(HotelSourceName.ALIBABA, criteria("IFN"), date(2026, 9, 5))
    assert search_url is not None
    parser = GenericHotelParser(
        HotelSourceName.ALIBABA,
        criteria("IFN"),
        date(2026, 9, 5),
        search_url,
        datetime(2026, 8, 11, tzinfo=UTC),
    )
    payload = {
        "name": {"fa": "عمارت سهروردی", "en": "Sohrevardi Isfahan"},
        "star": 4,
        "address": {"fa": "", "en": ""},
        "pricePerNight": 64_000_000,
        "currency": "IRR",
        "link": "ir-isfahan/isfahan-sohrevardi",
    }
    results = parser.parse_payloads([payload])
    assert len(results) == 1
    assert results[0].hotel_name == "عمارت سهروردی"
    assert results[0].star_rating == 4
    assert results[0].offers[0].amount_toman == Decimal("6400000")


def test_parser_extracts_price_from_nested_bundles_and_defaults_to_rial() -> None:
    search_url = build_hotel_search_url(
        HotelSourceName.SNAPPTRIP, criteria(), date(2026, 9, 10)
    )
    assert search_url is not None
    parser = GenericHotelParser(
        HotelSourceName.SNAPPTRIP,
        criteria(),
        date(2026, 9, 10),
        search_url,
        datetime(2026, 8, 11, tzinfo=UTC),
    )
    payload = {
        "id": 3317283,
        "name": "The Marmara Pera",
        "address": "Mesrutiyet Caddesi, Tepebasi, Istanbul",
        "star": 4,
        "available": True,
        "bundles": [
            {"price": 1_400_000_000, "final_price": 1_400_000_000},
            {"price": 1_328_283_648, "final_price": 1_328_283_648},
        ],
    }
    results = parser.parse_payloads([payload])
    assert len(results) == 1
    assert results[0].star_rating == 4
    assert results[0].offers[0].amount_toman == Decimal("132828364.8")


def test_parser_excludes_unavailable_snapptrip_style_hotel() -> None:
    search_url = build_hotel_search_url(
        HotelSourceName.SNAPPTRIP, criteria(), date(2026, 9, 10)
    )
    assert search_url is not None
    parser = GenericHotelParser(
        HotelSourceName.SNAPPTRIP,
        criteria(),
        date(2026, 9, 10),
        search_url,
        datetime(2026, 8, 11, tzinfo=UTC),
    )
    payload = {
        "name": "Sold Out Hotel",
        "star": 3,
        "available": False,
        "bundles": [{"final_price": 500_000_000}],
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
