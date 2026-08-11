from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.types import (
    AlertCriteria,
    FlightLeg,
    NormalizedItinerary,
    PriceKind,
    SellerOffer,
    SourceName,
)
from app.scrapers.links import validate_source_url

DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
UNAVAILABLE_STATUS_TERMS = (
    "تکمیلظرفیت",
    "ظرفیتتکمیل",
    "کنسلشده",
    "لغوشده",
    "ناموجود",
    "فروختهشد",
    "soldout",
    "unavailable",
    "cancelled",
    "canceled",
)


def _key_map(value: dict[str, Any]) -> dict[str, Any]:
    return {re.sub(r"[^a-z0-9]", "", str(key).lower()): item for key, item in value.items()}


def _first(mapping: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        normalized = re.sub(r"[^a-z0-9]", "", name.lower())
        if normalized in mapping and mapping[normalized] not in (None, ""):
            return mapping[normalized]
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        mapped = _key_map(value)
        value = _first(mapped, ["name", "displayName", "title", "code"])
    if value is None:
        return None
    return str(value).strip() or None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    raw = str(value).translate(DIGIT_TRANSLATION)
    raw = re.sub(r"[^0-9.]", "", raw)
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _normalized_status(value: Any) -> str:
    return re.sub(
        r"[\s_\-\u200c\u200f]+",
        "",
        str(value or "").translate(DIGIT_TRANSLATION).casefold(),
    )


def _contains_unavailable_status(value: Any) -> bool:
    normalized = _normalized_status(value)
    return any(term in normalized for term in UNAVAILABLE_STATUS_TERMS)


def _flag(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = _normalized_status(value)
    if normalized in {"true", "1", "yes", "بله"}:
        return True
    if normalized in {"false", "0", "no", "خیر"}:
        return False
    return None


def _candidate_is_unavailable(raw: dict[str, Any]) -> bool:
    mapped = _key_map(raw)
    availability = _first(
        mapped,
        ["isAvailable", "available", "isBookable", "bookable", "canBook", "isSellable"],
    )
    if availability is not None and _flag(availability) is False:
        return True
    disabled = _first(mapped, ["isDisabled", "disabled"])
    if disabled is not None and _flag(disabled) is True:
        return True
    remaining = _decimal(
        _first(mapped, ["seatsRemaining", "availableSeats", "remainingSeats"])
    )
    if remaining is not None and remaining <= 0:
        return True
    status = _first(
        mapped,
        ["status", "availabilityStatus", "flightStatus", "saleStatus", "statusText"],
    )
    return status is not None and _contains_unavailable_status(_text(status) or status)


def _card_is_unavailable(card: dict[str, Any]) -> bool:
    return bool(card.get("unavailable")) or _contains_unavailable_status(card.get("text"))


def _datetime(value: Any, fallback_date: date, timezone: ZoneInfo) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone)
    raw = str(value).strip().translate(DIGIT_TRANSLATION).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
        return parsed.replace(tzinfo=timezone) if parsed.tzinfo is None else parsed
    except ValueError:
        pass
    match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", raw)
    if match:
        return datetime.combine(
            fallback_date,
            time(int(match.group(1)), int(match.group(2))),
            tzinfo=timezone,
        )
    return None


class GenericFlightParser:
    """Conservative parser for captured first-party JSON and rendered result cards.

    It only emits a result when route, departure time, airline, and an allowed official
    link are all present. Site contract changes therefore fail closed.
    """

    def __init__(
        self,
        source: SourceName,
        criteria: AlertCriteria,
        outbound_date: date,
        return_date: date | None,
        search_url: str,
        observed_at: datetime,
    ) -> None:
        self.source = source
        self.criteria = criteria
        self.outbound_date = outbound_date
        self.return_date = return_date
        self.search_url = search_url
        self.observed_at = observed_at
        self.timezone = ZoneInfo(criteria.timezone)

    def parse_payloads(self, payloads: list[Any]) -> list[NormalizedItinerary]:
        candidates: list[dict[str, Any]] = []
        for payload in payloads:
            candidates.extend(self._candidate_dicts(payload))
        results: dict[str, NormalizedItinerary] = {}
        for candidate in candidates:
            itinerary = self._parse_candidate(candidate)
            if itinerary and self._matches(itinerary):
                existing = results.get(itinerary.fingerprint)
                if existing:
                    existing.offers.extend(itinerary.offers)
                else:
                    results[itinerary.fingerprint] = itinerary
        return list(results.values())

    def parse_dom_cards(self, cards: list[dict[str, Any]]) -> list[NormalizedItinerary]:
        results: list[NormalizedItinerary] = []
        for card in cards:
            if _card_is_unavailable(card):
                continue
            text_value = str(card.get("text", "")).translate(DIGIT_TRANSLATION)
            times = re.findall(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text_value)
            if not times:
                continue
            departure = datetime.combine(
                self.outbound_date,
                time(int(times[0][0]), int(times[0][1])),
                tzinfo=self.timezone,
            )
            flight_match = re.search(r"\b([A-Z]{2,3})\s*[- ]?(\d{2,4})\b", text_value)
            lines = [line.strip() for line in text_value.splitlines() if line.strip()]
            airline = lines[0] if lines else None
            if not airline:
                continue
            url = str(card.get("url") or self.search_url)
            if not validate_source_url(self.source, url):
                url = self.search_url
            amount_match = re.search(r"([\d,]{4,})\s*(تومان|ریال)", text_value)
            amount = _decimal(amount_match.group(1)) if amount_match else None
            currency = "IRT" if not amount_match or amount_match.group(2) == "تومان" else "IRR"
            amount_toman = amount / 10 if amount is not None and currency == "IRR" else amount
            leg = FlightLeg(
                origin=self.criteria.origin,
                destination=self.criteria.destination,
                departure=departure,
                airline=airline,
                flight_number=("".join(flight_match.groups()) if flight_match else None),
                cabin=self.criteria.cabin,
            )
            if self.return_date is not None:
                # A single rendered card is not proof of a complete round trip.
                continue
            results.append(
                NormalizedItinerary(
                    outbound=leg,
                    offers=[
                        SellerOffer(
                            source=self.source,
                            amount=amount,
                            currency=currency,
                            amount_toman=amount_toman,
                            price_kind=PriceKind.FROM,
                            booking_url=url,
                            observed_at=self.observed_at,
                        )
                    ],
                )
            )
        return results

    def exclude_unavailable_dom(
        self,
        itineraries: list[NormalizedItinerary],
        cards: list[dict[str, Any]],
    ) -> list[NormalizedItinerary]:
        unavailable: list[tuple[str, str, str, str]] = []
        for card in cards:
            if not _card_is_unavailable(card):
                continue
            text_value = str(card.get("text", "")).translate(DIGIT_TRANSLATION)
            time_match = re.search(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", text_value)
            if not time_match:
                continue
            provider = _normalized_status(card.get("provider"))
            provider_code = _normalized_status(card.get("provider_code"))
            flight_match = re.search(r"\b([A-Z]{2,3})\s*[- ]?(\d{2,4})\b", text_value)
            flight_number = (
                _normalized_status("".join(flight_match.groups())) if flight_match else ""
            )
            unavailable.append(
                (
                    f"{int(time_match.group(1)):02d}:{time_match.group(2)}",
                    provider,
                    provider_code,
                    flight_number,
                )
            )

        if not unavailable:
            return itineraries

        filtered: list[NormalizedItinerary] = []
        for itinerary in itineraries:
            local_departure = itinerary.outbound.departure.astimezone(self.timezone)
            departure_time = local_departure.strftime("%H:%M")
            airline = _normalized_status(itinerary.outbound.airline)
            flight_number = _normalized_status(itinerary.outbound.flight_number)
            blocked = any(
                departure_time == card_time
                and (
                    bool(card_flight and flight_number and card_flight == flight_number)
                    or bool(
                        provider
                        and airline
                        and (provider in airline or airline in provider)
                    )
                    or bool(
                        provider_code
                        and airline
                        and (provider_code in airline or airline in provider_code)
                    )
                    or bool(
                        provider_code
                        and flight_number
                        and flight_number.startswith(provider_code)
                    )
                )
                for card_time, provider, provider_code, card_flight in unavailable
            )
            if not blocked:
                filtered.append(itinerary)
        return filtered

    def _candidate_dicts(self, value: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if isinstance(value, list):
            for item in value:
                found.extend(self._candidate_dicts(item))
        elif isinstance(value, dict):
            mapped = _key_map(value)
            flight_markers = {
                "departuretime",
                "departuredatetime",
                "departuredate",
                "flightnumber",
                "airline",
                "outbound",
                "departure",
            }
            has_round_trip = "outbound" in mapped and any(
                key in mapped for key in ("return", "returnflight", "inbound", "backwardflight")
            )
            if has_round_trip or len(flight_markers.intersection(mapped)) >= 2:
                found.append(value)
            for item in value.values():
                if isinstance(item, (list, dict)):
                    found.extend(self._candidate_dicts(item))
        return found

    def _parse_leg(
        self,
        raw: dict[str, Any],
        fallback_date: date,
        default_origin: str,
        default_destination: str,
    ) -> FlightLeg | None:
        mapped = _key_map(raw)
        departure = _datetime(
            _first(
                mapped,
                ["departureDateTime", "departureTime", "departureDate", "departTime", "startTime"],
            ),
            fallback_date,
            self.timezone,
        )
        airline = _text(_first(mapped, ["airline", "airlineName", "carrier", "airlineTitle"]))
        if not departure or not airline:
            return None
        arrival = _datetime(
            _first(mapped, ["arrivalDateTime", "arrivalTime", "arrivalDate", "endTime"]),
            fallback_date,
            self.timezone,
        )
        return FlightLeg(
            origin=_text(_first(mapped, ["origin", "originIata", "departureAirport"]))
            or default_origin,
            destination=_text(_first(mapped, ["destination", "destinationIata", "arrivalAirport"]))
            or default_destination,
            departure=departure,
            arrival=arrival,
            airline=airline,
            flight_number=_text(_first(mapped, ["flightNumber", "flightNo", "number"])),
            cabin=self.criteria.cabin,
            ticket_type=_text(_first(mapped, ["ticketType", "flightType", "fareType"])),
            baggage=_text(_first(mapped, ["baggage", "baggageAllowance"])),
        )

    def _parse_candidate(self, raw: dict[str, Any]) -> NormalizedItinerary | None:
        if _candidate_is_unavailable(raw):
            return None
        mapped = _key_map(raw)
        outbound_raw = _first(mapped, ["outbound", "departure", "outboundFlight", "goingFlight"])
        outbound = self._parse_leg(
            outbound_raw if isinstance(outbound_raw, dict) else raw,
            self.outbound_date,
            self.criteria.origin,
            self.criteria.destination,
        )
        if not outbound:
            return None

        return_leg = None
        if self.return_date:
            return_raw = _first(mapped, ["return", "returnFlight", "inbound", "backwardFlight"])
            if not isinstance(return_raw, dict):
                return None
            return_leg = self._parse_leg(
                return_raw,
                self.return_date,
                self.criteria.destination,
                self.criteria.origin,
            )
            if not return_leg:
                return None

        amount = _decimal(
            _first(
                mapped,
                ["totalPrice", "payableAmount", "price", "adultPrice", "displayPrice", "amount"],
            )
        )
        currency_raw = (
            _text(_first(mapped, ["currency", "currencyCode", "priceUnit"])) or "IRT"
        ).upper()
        currency = "IRR" if currency_raw in {"IRR", "RIAL", "ریال"} else "IRT"
        amount_toman = amount / 10 if amount is not None and currency == "IRR" else amount
        price_kind = (
            PriceKind.TOTAL
            if _first(mapped, ["totalPrice", "payableAmount"])
            else PriceKind.FROM
        )
        url = _text(_first(mapped, ["bookingUrl", "deepLink", "url", "link"])) or self.search_url
        if not validate_source_url(self.source, url):
            url = self.search_url
        return NormalizedItinerary(
            outbound=outbound,
            return_leg=return_leg,
            offers=[
                SellerOffer(
                    source=self.source,
                    amount=amount,
                    currency=currency,
                    amount_toman=amount_toman,
                    price_kind=price_kind,
                    seats_remaining=_first(
                        mapped, ["seatsRemaining", "availableSeats", "remainingSeats"]
                    ),
                    booking_url=url,
                    observed_at=self.observed_at,
                )
            ],
        )

    def _matches(self, itinerary: NormalizedItinerary) -> bool:
        outbound_local = itinerary.outbound.departure.astimezone(self.timezone)
        if not (
            self.criteria.outbound_times.start
            <= outbound_local.time().replace(tzinfo=None)
            <= self.criteria.outbound_times.end
        ):
            return False
        if self.return_date:
            if not itinerary.return_leg or not self.criteria.return_times:
                return False
            return_local = itinerary.return_leg.departure.astimezone(self.timezone)
            if not (
                self.criteria.return_times.start
                <= return_local.time().replace(tzinfo=None)
                <= self.criteria.return_times.end
            ):
                return False
        return True
