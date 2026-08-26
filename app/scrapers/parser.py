from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
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
from app.scrapers.text_utils import DIGIT_TRANSLATION
from app.scrapers.text_utils import contains_unavailable_status as _contains_unavailable_status
from app.scrapers.text_utils import decimal as _decimal
from app.scrapers.text_utils import first as _first
from app.scrapers.text_utils import flag as _flag
from app.scrapers.text_utils import key_map as _key_map
from app.scrapers.text_utils import normalized_status as _normalized_status
from app.scrapers.text_utils import text as _text


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


REMAINING_SEATS_PATTERN = re.compile(
    r"(?:ظرفیت|صندلی)[^\d]{0,12}(\d{1,3})|(\d{1,3})[^\S\r\n]{0,4}(?:صندلی|ظرفیت)[^\d]{0,12}(باقی|باقیمانده|خالی)"
)


def _remaining_seats_are_zero(text_value: str) -> bool:
    match = REMAINING_SEATS_PATTERN.search(text_value)
    if not match:
        return False
    digits = match.group(1) or match.group(2)
    return digits is not None and int(digits) == 0


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
        return self._collapse_generic_links(list(results.values()))

    def parse_dom_cards(self, cards: list[dict[str, Any]]) -> list[NormalizedItinerary]:
        results: dict[str, NormalizedItinerary] = {}
        for card in cards:
            if _card_is_unavailable(card):
                continue
            text_value = str(card.get("text", "")).translate(DIGIT_TRANSLATION)
            if _remaining_seats_are_zero(text_value):
                continue
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
            raw_url = card.get("url")
            url = str(raw_url) if raw_url else self.search_url
            generic_link = not card.get("has_specific_link") or not validate_source_url(
                self.source, url
            )
            if generic_link:
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
            itinerary = NormalizedItinerary(
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
                        metadata={"generic_link": True} if generic_link else {},
                    )
                ],
            )
            existing = results.get(itinerary.fingerprint)
            if existing:
                existing.offers.extend(itinerary.offers)
            else:
                results[itinerary.fingerprint] = itinerary
        return self._collapse_generic_links(list(results.values()))

    def _collapse_generic_links(
        self, itineraries: list[NormalizedItinerary]
    ) -> list[NormalizedItinerary]:
        """A booking_url that falls back to the plain search page cannot distinguish one
        itinerary from another. When several itineraries share that same non-specific link
        for a source, keep only the cheapest offer instead of repeating an identical link
        across every result.
        """
        best: dict[SourceName, SellerOffer] = {}
        for itinerary in itineraries:
            for offer in itinerary.offers:
                if not offer.metadata.get("generic_link"):
                    continue
                current = best.get(offer.source)
                price = (
                    offer.amount_toman if offer.amount_toman is not None else Decimal("Infinity")
                )
                current_price = (
                    current.amount_toman if current and current.amount_toman is not None else None
                )
                if current is None or price < (
                    current_price if current_price is not None else Decimal("Infinity")
                ):
                    best[offer.source] = offer
        keep_offer_ids = {id(offer) for offer in best.values()}
        collapsed: list[NormalizedItinerary] = []
        for itinerary in itineraries:
            kept_offers = [
                offer
                for offer in itinerary.offers
                if not offer.metadata.get("generic_link") or id(offer) in keep_offer_ids
            ]
            if kept_offers:
                collapsed.append(itinerary.model_copy(update={"offers": kept_offers}))
        return collapsed

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
        raw_url = _text(_first(mapped, ["bookingUrl", "deepLink", "url", "link"]))
        url = raw_url or self.search_url
        generic_link = not raw_url or not validate_source_url(self.source, url)
        if generic_link:
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
                    metadata={"generic_link": True} if generic_link else {},
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
