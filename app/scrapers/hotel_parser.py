from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.domain.types import (
    HotelCriteria,
    HotelOffer,
    HotelPriceKind,
    HotelSourceName,
    NormalizedHotel,
)
from app.scrapers.hotel_links import checkout_date, validate_hotel_source_url
from app.scrapers.text_utils import contains_unavailable_status as _contains_unavailable_status
from app.scrapers.text_utils import decimal as _decimal
from app.scrapers.text_utils import first as _first
from app.scrapers.text_utils import flag as _flag
from app.scrapers.text_utils import key_map as _key_map
from app.scrapers.text_utils import text as _text

STAR_PATTERN = re.compile(r"(\d(?:\.\d)?)\s*(?:ستاره|star)", re.IGNORECASE)

# Some sites (confirmed: Snapptrip) report prices in Rial with no explicit currency
# field on the hotel object; everything else here defaults to Toman as elsewhere in
# the codebase.
DEFAULT_CURRENCY_BY_SOURCE = {HotelSourceName.SNAPPTRIP: "IRR"}


def _cheapest_bundle_price(mapped: dict[str, Any]) -> Any:
    bundles = _first(mapped, ["bundles", "rooms", "offers"])
    if not isinstance(bundles, list):
        return None
    best: Any = None
    for bundle in bundles:
        if not isinstance(bundle, dict):
            continue
        bundle_mapped = _key_map(bundle)
        price = _first(bundle_mapped, ["finalPrice", "discountedPrice", "price"])
        price_decimal = _decimal(price)
        if price_decimal is None:
            continue
        if best is None or price_decimal < _decimal(best):
            best = price
    return best


def _card_is_unavailable(card: dict[str, Any]) -> bool:
    return bool(card.get("unavailable")) or _contains_unavailable_status(card.get("text"))


def _candidate_is_unavailable(raw: dict[str, Any]) -> bool:
    mapped = _key_map(raw)
    availability = _first(mapped, ["isAvailable", "available", "isBookable", "bookable"])
    if availability is not None and _flag(availability) is False:
        return True
    remaining = _decimal(_first(mapped, ["roomsRemaining", "availableRooms", "remainingRooms"]))
    if remaining is not None and remaining <= 0:
        return True
    status = _first(mapped, ["status", "availabilityStatus", "saleStatus", "statusText"])
    return status is not None and _contains_unavailable_status(_text(status) or status)


class GenericHotelParser:
    """Conservative parser for captured first-party JSON and rendered hotel cards.

    Mirrors app/scrapers/parser.py's fail-closed approach: a result is only emitted
    when a hotel name, a price, and an allowed official link are all present.
    """

    def __init__(
        self,
        source: HotelSourceName,
        criteria: HotelCriteria,
        checkin: date,
        search_url: str,
        observed_at: datetime,
    ) -> None:
        self.source = source
        self.criteria = criteria
        self.checkin = checkin
        self.checkout = checkout_date(checkin, criteria.nights)
        self.search_url = search_url
        self.observed_at = observed_at

    def parse_payloads(self, payloads: list[Any]) -> list[NormalizedHotel]:
        candidates: list[dict[str, Any]] = []
        for payload in payloads:
            candidates.extend(self._candidate_dicts(payload))
        results: dict[str, NormalizedHotel] = {}
        for candidate in candidates:
            hotel = self._parse_candidate(candidate)
            if hotel:
                existing = results.get(hotel.fingerprint)
                if existing:
                    existing.offers.extend(hotel.offers)
                else:
                    results[hotel.fingerprint] = hotel
        return self._collapse_generic_links(list(results.values()))

    def parse_dom_cards(self, cards: list[dict[str, Any]]) -> list[NormalizedHotel]:
        results: dict[str, NormalizedHotel] = {}
        for card in cards:
            if _card_is_unavailable(card):
                continue
            text_value = str(card.get("text", ""))
            lines = [line.strip() for line in text_value.splitlines() if line.strip()]
            if not lines:
                continue
            hotel_name = lines[0]
            amount_match = re.search(r"([\d,]{4,})\s*(تومان|ریال)", text_value)
            amount = _decimal(amount_match.group(1)) if amount_match else None
            if amount is None:
                continue
            currency = "IRT" if not amount_match or amount_match.group(2) == "تومان" else "IRR"
            amount_toman = amount / 10 if currency == "IRR" else amount
            star_match = STAR_PATTERN.search(text_value)
            star_rating = int(round(float(star_match.group(1)))) if star_match else None
            raw_url = card.get("url")
            url = str(raw_url) if raw_url else self.search_url
            generic_link = not card.get("has_specific_link") or not validate_hotel_source_url(
                self.source, url
            )
            if generic_link:
                url = self.search_url
            hotel = NormalizedHotel(
                hotel_name=hotel_name,
                city=self.criteria.destination,
                star_rating=star_rating,
                checkin=self.checkin,
                checkout=self.checkout,
                offers=[
                    HotelOffer(
                        source=self.source,
                        hotel_name=hotel_name,
                        star_rating=star_rating,
                        amount=amount,
                        currency=currency,
                        amount_toman=amount_toman,
                        price_kind=HotelPriceKind.PER_NIGHT,
                        booking_url=url,
                        observed_at=self.observed_at,
                        metadata={"generic_link": True} if generic_link else {},
                    )
                ],
            )
            existing = results.get(hotel.fingerprint)
            if existing:
                existing.offers.extend(hotel.offers)
            else:
                results[hotel.fingerprint] = hotel
        return self._collapse_generic_links(list(results.values()))

    def _collapse_generic_links(self, hotels: list[NormalizedHotel]) -> list[NormalizedHotel]:
        """See GenericFlightParser._collapse_generic_links: a link that falls back to the
        plain search page cannot distinguish one hotel from another, so keep only the
        cheapest such offer per source instead of repeating an identical link.
        """
        best: dict[HotelSourceName, HotelOffer] = {}
        for hotel in hotels:
            for offer in hotel.offers:
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
        collapsed: list[NormalizedHotel] = []
        for hotel in hotels:
            kept_offers = [
                offer
                for offer in hotel.offers
                if not offer.metadata.get("generic_link") or id(offer) in keep_offer_ids
            ]
            if kept_offers:
                collapsed.append(hotel.model_copy(update={"offers": kept_offers}))
        return collapsed

    def _candidate_dicts(self, value: Any) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if isinstance(value, list):
            for item in value:
                found.extend(self._candidate_dicts(item))
        elif isinstance(value, dict):
            mapped = _key_map(value)
            hotel_markers = {
                "hotelname",
                "name",
                "stars",
                "star",
                "starrating",
                "price",
                "pricepernight",
                "totalprice",
                "address",
                "bundles",
            }
            has_name = bool(_first(mapped, ["hotelName", "name", "title"]))
            has_price = bool(
                _first(mapped, ["price", "pricePerNight", "totalPrice", "amount"])
                or _cheapest_bundle_price(mapped)
            )
            if has_name and has_price and len(hotel_markers.intersection(mapped)) >= 2:
                found.append(value)
            for item in value.values():
                if isinstance(item, (list, dict)):
                    found.extend(self._candidate_dicts(item))
        return found

    def _parse_candidate(self, raw: dict[str, Any]) -> NormalizedHotel | None:
        if _candidate_is_unavailable(raw):
            return None
        mapped = _key_map(raw)
        hotel_name = _text(_first(mapped, ["hotelName", "name", "title"]))
        if not hotel_name:
            return None
        flat_amount = _first(
            mapped, ["totalPrice", "pricePerNight", "price", "amount", "displayPrice"]
        )
        bundle_amount = _cheapest_bundle_price(mapped) if flat_amount is None else None
        amount = _decimal(flat_amount if flat_amount is not None else bundle_amount)
        if amount is None:
            return None
        default_currency = DEFAULT_CURRENCY_BY_SOURCE.get(self.source, "IRT")
        currency_raw = (
            _text(_first(mapped, ["currency", "currencyCode", "priceUnit"])) or default_currency
        ).upper()
        currency = "IRR" if currency_raw in {"IRR", "RIAL", "ریال"} else "IRT"
        amount_toman = amount / 10 if currency == "IRR" else amount
        price_kind = (
            HotelPriceKind.TOTAL
            if flat_amount is None or _first(mapped, ["totalPrice"])
            else HotelPriceKind.PER_NIGHT
        )
        star_decimal = _decimal(
            _first(mapped, ["stars", "star", "starRating", "hotelStars", "rating"])
        )
        star_rating = int(star_decimal) if star_decimal is not None else None
        raw_url = _text(_first(mapped, ["bookingUrl", "deepLink", "url", "link"]))
        url = raw_url or self.search_url
        generic_link = not raw_url or not validate_hotel_source_url(self.source, url)
        if generic_link:
            url = self.search_url
        return NormalizedHotel(
            hotel_name=hotel_name,
            city=self.criteria.destination,
            address=_text(_first(mapped, ["address", "location"])),
            star_rating=star_rating,
            checkin=self.checkin,
            checkout=self.checkout,
            offers=[
                HotelOffer(
                    source=self.source,
                    hotel_name=hotel_name,
                    star_rating=star_rating,
                    amount=amount,
                    currency=currency,
                    amount_toman=amount_toman,
                    price_kind=price_kind,
                    rooms_remaining=_first(mapped, ["roomsRemaining", "availableRooms"]),
                    booking_url=url,
                    observed_at=self.observed_at,
                    metadata={"generic_link": True} if generic_link else {},
                )
            ],
        )
