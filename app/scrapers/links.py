from __future__ import annotations

from datetime import date
from urllib.parse import urlencode, urlparse

from app.core.dates import jalali_date_string
from app.domain.types import AlertCriteria, CabinClass, SourceName

SOURCE_HOSTS = {
    SourceName.ALIBABA: {"www.alibaba.ir", "alibaba.ir"},
    SourceName.FLIGHTIO: {"flightio.com", "www.flightio.com"},
    SourceName.TRIP: {"trip.ir", "www.trip.ir"},
    SourceName.RESPINA24: {"respina24.ir", "www.respina24.ir"},
}


def build_search_url(
    source: SourceName,
    criteria: AlertCriteria,
    outbound_date: date,
    return_date: date | None,
) -> str:
    p = criteria.passengers
    route = f"{criteria.origin}-{criteria.destination}"
    if source == SourceName.ALIBABA:
        query = {
            "adult": p.adults,
            "child": p.children,
            "infant": p.infants,
            "departing": jalali_date_string(outbound_date),
        }
        if return_date:
            query["returning"] = jalali_date_string(return_date)
        if criteria.cabin != CabinClass.ECONOMY:
            query["flightClass"] = criteria.cabin.value
        return f"https://www.alibaba.ir/flights/{route}?{urlencode(query)}"

    if source == SourceName.TRIP:
        query = {
            "origin": criteria.origin,
            "destination": criteria.destination,
            "outbound": outbound_date.isoformat(),
            "adults": p.adults,
            "children": p.children,
            "infants": p.infants,
            "cabin": criteria.cabin.value,
            "redirectSearch": "true",
        }
        if return_date:
            query["inbound"] = return_date.isoformat()
        return f"https://trip.ir/flight/booking/search?{urlencode(query)}"

    if source == SourceName.FLIGHTIO:
        query = {
            "departureDate": outbound_date.isoformat(),
            "adult": p.adults,
            "child": p.children,
            "infant": p.infants,
            "cabin": criteria.cabin.value,
        }
        if return_date:
            query["returnDate"] = return_date.isoformat()
        return f"https://flightio.com/flight/{route}?{urlencode(query)}"

    if source == SourceName.RESPINA24:
        query = {
            "departureDate": outbound_date.isoformat(),
            "adult": p.adults,
            "child": p.children,
            "infant": p.infants,
            "cabin": criteria.cabin.value,
        }
        if return_date:
            query["returnDate"] = return_date.isoformat()
        return f"https://respina24.ir/flight/{route}?{urlencode(query)}"
    raise ValueError(f"Unsupported source: {source}")


def validate_source_url(source: SourceName, url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in SOURCE_HOSTS[source]

