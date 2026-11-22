"""Approved offline observations and the self-contained demonstration data."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, Field, HttpUrl, StringConstraints, field_validator, model_validator

from src.domain.portfolio import Currency, FrozenRecord, PositiveDecimal

from .valuation import FIXTURES, IDENTIFIERS, METHOD

InstrumentKey = Annotated[str, StringConstraints(pattern=r"^(ASX|XASX|XNAS|XNYS|ARCX):[A-Z0-9.\-]{1,16}$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class Listing(FrozenRecord):
    label: ShortText
    currency: Currency


class Price(FrozenRecord):
    value: PositiveDecimal
    observed_at: AwareDatetime
    available_at: AwareDatetime

    @model_validator(mode="after")
    def timely(self):
        if self.available_at < self.observed_at:
            raise ValueError("Availability cannot precede observation.")
        return self


class Period(FrozenRecord):
    cutoff: AwareDatetime
    prices: dict[InstrumentKey, Price]
    aud_per_usd: Price | None = None

    @model_validator(mode="after")
    def no_future_data(self):
        prices = list(self.prices.values())
        if self.aud_per_usd:
            prices.append(self.aud_per_usd)
        if any(price.available_at > self.cutoff for price in prices):
            raise ValueError("Market observations must be available by the report cutoff.")
        return self


class Event(FrozenRecord):
    id: ShortText
    instrument: InstrumentKey
    title: ShortText
    category: ShortText
    available_at: AwareDatetime
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def secure_link(cls, url):
        if url.scheme != "https" or url.username or url.password:
            raise ValueError("Use an HTTPS evidence link without credentials.")
        return url


class ApprovedMarketFile(BaseModel):
    source: ShortText
    revision: ShortText
    listings: dict[InstrumentKey, Listing] = Field(min_length=1, max_length=5000)
    periods: dict[date, Period] = Field(min_length=1, max_length=1000)
    events: list[Event] = Field(default_factory=list, max_length=5000)

    @model_validator(mode="after")
    def known_listings(self):
        if any(period.prices.keys() - self.listings.keys() for period in self.periods.values()):
            raise ValueError("A market observation references an unknown listing.")
        if any(event.instrument not in self.listings for event in self.events):
            raise ValueError("An event references an unknown listing.")
        if len({event.id for event in self.events}) != len(self.events):
            raise ValueError("Event IDs must be unique.")
        return self


@dataclass(frozen=True)
class Market:
    identifiers: dict[str, tuple[str, str]]
    periods: dict
    source: str
    revision: str
    demo: bool
    events: tuple[Event, ...] = ()

    @property
    def dates(self):
        return sorted(self.periods)

    def eligible_dates(self):
        now = datetime.now(ZoneInfo("Australia/Sydney"))
        return [day for day in self.dates if day <= now.date().isoformat()
                and (self.demo or self.periods[day].cutoff <= now)]

    def review_inputs(self, day):
        if self.demo:
            return {"market_input": self.periods[day], "identifiers": self.identifiers}
        period = self.periods[day]
        return {
            "market_input": (
                {key: str(value.value) for key, value in period.prices.items()},
                str(period.aud_per_usd.value) if period.aud_per_usd else None,
            ),
            "identifiers": self.identifiers,
            "source": self.source,
            "revision": self.revision,
            "cutoff": period.cutoff.isoformat(),
            "price_dates": {key: value.observed_at.isoformat() for key, value in period.prices.items()},
            "fx_date": period.aud_per_usd.observed_at.isoformat() if period.aud_per_usd else None,
            "price_availability": {key: value.available_at.isoformat() for key, value in period.prices.items()},
            "fx_availability": period.aud_per_usd.available_at.isoformat() if period.aud_per_usd else None,
        }


def synthetic_market():
    return Market(IDENTIFIERS, FIXTURES, "Synthetic market fixtures", METHOD, True)


def configured_market(demo):
    if demo:
        return synthetic_market()
    path = os.environ.get("WORKBENCH_APPROVED_MARKET_FILE")
    if not path or os.environ.get("WORKBENCH_APPROVED_DATA") != "1":
        raise RuntimeError("Supply the approved market observation file and confirm its use entitlement.")
    with Path(path).open("rb") as stream:
        data = stream.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise RuntimeError("The market observation file exceeds 20 MiB.")
    market = ApprovedMarketFile.model_validate(json.loads(data, parse_float=Decimal))
    return Market(
        {**{key: (item.currency, item.label) for key, item in market.listings.items()},
         "CASH:AUD": ("AUD", "AUD cash"), "CASH:USD": ("USD", "USD cash")},
        {day.isoformat(): value for day, value in market.periods.items()},
        market.source, market.revision, False, tuple(market.events),
    )


DEMO_EVENTS = (
    {"id": "sample-bhp-brief", "instrument": "ASX:BHP", "date": "2026-11-18",
     "title": "Illustrative operations update", "category": "Company announcement"},
    {"id": "sample-apple-calendar", "instrument": "XNAS:AAPL", "date": "2026-11-19",
     "title": "Illustrative reporting calendar update", "category": "Earnings calendar"},
)


def holding_events(report, market):
    holdings = {row["instrument"] for row in report["positions"]}
    if market.demo:
        return [event for event in DEMO_EVENTS
                if event["instrument"] in holdings and event["date"] <= report["snapshot_date"]]
    if not report.get("cutoff") or report.get("revision") != market.revision:
        return []
    cutoff = datetime.fromisoformat(report["cutoff"])
    events = sorted(market.events, key=lambda item: (item.available_at, item.id), reverse=True)
    return [{**item.model_dump(mode="json"), "date": item.available_at.date().isoformat()}
            for item in events if item.instrument in holdings and item.available_at <= cutoff][:50]
