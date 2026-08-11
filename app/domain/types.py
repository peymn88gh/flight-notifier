from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, model_validator


class TripType(StrEnum):
    ONE_WAY = "one_way"
    ROUND_TRIP = "round_trip"


class CabinClass(StrEnum):
    ECONOMY = "economy"
    BUSINESS = "business"


class AlertStatus(StrEnum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SourceName(StrEnum):
    ALIBABA = "alibaba"
    FLIGHTIO = "flightio"
    TRIP = "trip"
    RESPINA24 = "respina24"


class PriceKind(StrEnum):
    TOTAL = "total"
    PER_ADULT = "per_adult"
    FROM = "from"


class PassengerCounts(BaseModel):
    adults: int = Field(default=1, ge=1, le=9)
    children: int = Field(default=0, ge=0, le=8)
    infants: int = Field(default=0, ge=0, le=9)

    @model_validator(mode="after")
    def validate_party(self) -> PassengerCounts:
        if self.infants > self.adults:
            raise ValueError("Each infant must travel with an adult")
        if self.adults + self.children > 9:
            raise ValueError("At most nine seated passengers are supported")
        return self


class DateWindow(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_window(self) -> DateWindow:
        if self.end < self.start:
            raise ValueError("Date range end cannot be before its start")
        if (self.end - self.start).days > 6:
            raise ValueError("Date ranges may contain at most seven days")
        return self


class TimeWindow(BaseModel):
    start: time = time(0, 0)
    end: time = time(23, 59)

    @model_validator(mode="after")
    def validate_window(self) -> TimeWindow:
        if self.end < self.start:
            raise ValueError("Overnight time windows are not supported")
        return self


class AlertCriteria(BaseModel):
    trip_type: TripType
    origin: str = Field(pattern=r"^[A-Z0-9_]{3,16}$")
    destination: str = Field(pattern=r"^[A-Z0-9_]{3,16}$")
    outbound_dates: DateWindow
    outbound_times: TimeWindow = Field(default_factory=TimeWindow)
    return_dates: DateWindow | None = None
    return_times: TimeWindow | None = None
    passengers: PassengerCounts = Field(default_factory=PassengerCounts)
    cabin: CabinClass = CabinClass.ECONOMY
    timezone: str = "Asia/Tehran"

    @model_validator(mode="after")
    def validate_criteria(self) -> AlertCriteria:
        if self.origin == self.destination:
            raise ValueError("Origin and destination must be different")
        if self.trip_type == TripType.ROUND_TRIP:
            if not self.return_dates or not self.return_times:
                raise ValueError("Round trips require return date and time ranges")
            if self.return_dates.end < self.outbound_dates.start:
                raise ValueError("Return range must contain a date on or after outbound travel")
        elif self.return_dates or self.return_times:
            raise ValueError("One-way alerts cannot include return criteria")
        return self


class FlightLeg(BaseModel):
    origin: str
    destination: str
    departure: datetime
    arrival: datetime | None = None
    airline: str
    flight_number: str | None = None
    cabin: CabinClass = CabinClass.ECONOMY
    ticket_type: str | None = None
    baggage: str | None = None


class SellerOffer(BaseModel):
    source: SourceName
    amount: Decimal | None = None
    currency: str = "IRT"
    amount_toman: Decimal | None = None
    price_kind: PriceKind = PriceKind.FROM
    seats_remaining: int | None = None
    booking_url: HttpUrl
    observed_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedItinerary(BaseModel):
    outbound: FlightLeg
    return_leg: FlightLeg | None = None
    offers: list[SellerOffer] = Field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        identity = {
            "outbound": self._leg_identity(self.outbound),
            "return": self._leg_identity(self.return_leg) if self.return_leg else None,
        }
        raw = json.dumps(identity, sort_keys=True, ensure_ascii=True).encode()
        return hashlib.sha256(raw).hexdigest()[:24]

    @staticmethod
    def _leg_identity(leg: FlightLeg | None) -> dict[str, Any] | None:
        if leg is None:
            return None
        return {
            "origin": leg.origin,
            "destination": leg.destination,
            "departure": leg.departure.isoformat(),
            "airline": leg.airline.strip().casefold(),
            "flight_number": (leg.flight_number or "").replace(" ", "").upper(),
            "cabin": leg.cabin.value,
            "ticket_type": (leg.ticket_type or "").casefold(),
        }


class SiteSearchResult(BaseModel):
    source: SourceName
    itineraries: list[NormalizedItinerary] = Field(default_factory=list)
    searched_at: datetime
    search_url: HttpUrl
    error: str | None = None
