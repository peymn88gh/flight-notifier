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


def destination_city_fa(destination_code: str) -> str | None:
    destination = _destinations().get(destination_code)
    return destination.get("city_fa") if destination else None


def checkout_date(checkin: date, nights: int) -> date:
    return checkin + timedelta(days=nights)


def build_hotel_search_url(
    source: HotelSourceName,
    criteria: HotelCriteria,
    checkin: date,
) -> str | None:
    """Real, verified search URLs per site (checked live against each site on 2026-08-26).

    Unlike app/scrapers/links.py's flight URLs, most hotel sites here do NOT accept a
    plain query-string deep link into a working results page - each site's own quirks
    are handled explicitly below rather than guessed generically:

    - alibaba.ir: `departing`/`returning` on the existing slug path works directly.
    - respina24.ir: domestic and international hotels are two different site sections
      with different path shapes and different date-param names.
    - snapptrip.com: only international hotels have a confirmed working path
      (`/international-hotel/{city}-{country_code}`); domestic slugs are left null
      since no working pattern was verified, and this returns None for those.
    - trip.ir: has no query-string deep link at all - its search box requires picking
      a destination from a live autocomplete, which resolves to an internal numeric
      city id you cannot construct from a slug. The plain landing page is still a
      real, working page, just without dates pre-filled; PlaywrightHotelAdapter drives
      the actual interactive search separately (see hotel_adapters.py).
    """
    destination = _destinations().get(criteria.destination)
    if not destination:
        return None
    slug = destination.get("slugs", {}).get(source.value)
    checkout = checkout_date(checkin, criteria.nights)
    occupants = criteria.occupancy.adults + criteria.occupancy.children

    if source == HotelSourceName.ALIBABA:
        if not slug:
            return None
        query = {"departing": checkin.isoformat(), "returning": checkout.isoformat()}
        return f"https://www.alibaba.ir/hotel/{slug}?{urlencode(query)}"

    if source == HotelSourceName.TRIP:
        if not slug:
            return None
        return f"https://www.trip.ir/hotel/{slug}"

    if source == HotelSourceName.RESPINA24:
        if destination.get("is_domestic", True):
            if not slug:
                return None
            query = {
                "departing": checkin.isoformat(),
                "returning": checkout.isoformat(),
                "adults": occupants,
                "rooms": criteria.rooms,
                "childages": "",
            }
            return f"https://respina24.ir/hotel/{slug}?{urlencode(query)}"
        country_en = destination.get("country_en")
        city_en = destination.get("city_en")
        if not country_en or not city_en:
            return None
        query = {
            "checkin": checkin.isoformat(),
            "checkout": checkout.isoformat(),
            "adults": occupants,
            "rooms": criteria.rooms,
            "childages": "",
            "nationality": "IR",
        }
        path = f"{quote(country_en)}/{quote(city_en)}"
        return f"https://respina24.ir/internationalhotel/search/{path}?{urlencode(query)}"

    if source == HotelSourceName.SNAPPTRIP:
        if not slug:
            return None
        query = {
            "date_from": checkin.isoformat(),
            "date_to": checkout.isoformat(),
            "occupants": occupants,
        }
        return f"https://www.snapptrip.com/international-hotel/{slug}?{urlencode(query)}"

    raise ValueError(f"Unsupported hotel source: {source}")


def validate_hotel_source_url(source: HotelSourceName, url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in SOURCE_HOSTS[source]
