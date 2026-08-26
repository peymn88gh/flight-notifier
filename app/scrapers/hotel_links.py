from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

from app.domain.types import HotelCriteria, HotelSourceName

SOURCE_HOSTS = {
    HotelSourceName.ALIBABA: {"www.alibaba.ir", "alibaba.ir"},
    HotelSourceName.TRIP: {"trip.ir", "www.trip.ir"},
    HotelSourceName.RESPINA24: {"respina24.ir", "www.respina24.ir"},
    HotelSourceName.SNAPPTRIP: {"snapptrip.com", "www.snapptrip.com"},
}

_DESTINATIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "hotel_destinations.json"


@lru_cache
def _destinations() -> dict[str, dict]:
    values = json.loads(_DESTINATIONS_PATH.read_text(encoding="utf-8"))
    return {item["code"]: item for item in values}


def destination_slug(source: HotelSourceName, destination_code: str) -> str | None:
    destination = _destinations().get(destination_code)
    if not destination:
        return None
    return destination.get("slugs", {}).get(source.value)


def checkout_date(checkin: date, nights: int) -> date:
    return checkin + timedelta(days=nights)


def build_hotel_search_url(
    source: HotelSourceName,
    criteria: HotelCriteria,
    checkin: date,
) -> str | None:
    """Best-effort search URL per site, mirroring app/scrapers/links.py.

    Slugs come from app/data/hotel_destinations.json and were captured from each
    site's live URL structure at write time; they are not guaranteed to stay
    correct if a site restructures its paths. The scraper does not depend on the
    URL itself being exact - it captures first-party JSON/DOM from whatever page
    loads, and fails closed if nothing verifiable is found.
    """
    slug = destination_slug(source, criteria.destination)
    if not slug:
        return None
    checkout = checkout_date(checkin, criteria.nights)
    occupancy = criteria.occupancy

    if source == HotelSourceName.ALIBABA:
        query = {
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "room": criteria.rooms,
            "adult": occupancy.adults,
            "child": occupancy.children,
        }
        return f"https://www.alibaba.ir/hotel/{slug}?{urlencode(query)}"

    if source == HotelSourceName.TRIP:
        query = {
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "rooms": criteria.rooms,
            "adults": occupancy.adults,
            "children": occupancy.children,
        }
        return f"https://www.trip.ir/hotel/{slug}?{urlencode(query)}"

    if source == HotelSourceName.RESPINA24:
        query = {
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "room": criteria.rooms,
            "adult": occupancy.adults,
            "child": occupancy.children,
        }
        return f"https://respina24.ir/hotel/{slug}?{urlencode(query)}"

    if source == HotelSourceName.SNAPPTRIP:
        query = {
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "rooms": criteria.rooms,
            "adults": occupancy.adults,
        }
        path = quote(f"رزرو-هتل/{slug}")
        return f"https://www.snapptrip.com/{path}?{urlencode(query)}"

    raise ValueError(f"Unsupported hotel source: {source}")


def validate_hotel_source_url(source: HotelSourceName, url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in SOURCE_HOSTS[source]
