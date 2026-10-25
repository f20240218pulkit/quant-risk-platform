"""Single-currency holdings and valuation contracts for manual/CSV/broker adapters.

Provider symbol resolution is a separate responsibility. Constructing these
records does not verify that a declared exchange or quote is authoritative.
"""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PositiveDecimal = Annotated[Decimal, Field(gt=0, le=Decimal("1e15"), max_digits=28, decimal_places=10, allow_inf_nan=False)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0, le=Decimal("1e30"), max_digits=48, decimal_places=28, allow_inf_nan=False)]
Weight = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
Currency = Literal["AUD", "USD"]


class FrozenRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Instrument(FrozenRecord):
    instrument_id: str = Field(min_length=1, max_length=128)
    ticker: str = Field(min_length=1, max_length=32)
    exchange: str = Field(min_length=1, max_length=32)
    currency: Currency
    asset_type: Literal["share", "etf"]
    provider_symbol: str = Field(min_length=1, max_length=32)
    price_multiplier: PositiveDecimal = Decimal("1")

    @field_validator("instrument_id", "ticker", "exchange", "provider_symbol", mode="before")
    @classmethod
    def meaningful_identifier(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Instrument identifiers must be non-empty text.")
        return value.strip()



class Position(FrozenRecord):
    instrument: Instrument
    quantity: PositiveDecimal
    source_rows: tuple[int, ...] = ()


class HoldingsSnapshot(FrozenRecord):
    base_currency: Currency
    positions: tuple[Position, ...] = Field(min_length=1, max_length=50)
    cash: NonNegativeDecimal = Decimal("0")
    source: Literal["manual", "csv", "broker"]
    confirmed_at: datetime

    @model_validator(mode="after")
    def consistent(self):
        if self.confirmed_at.utcoffset() is None:
            raise ValueError("Confirmation time must include a timezone.")
        ids = [p.instrument.instrument_id for p in self.positions]
        if len(ids) != len(set(ids)):
            raise ValueError("Reconcile duplicate instruments before confirming.")
        if any(p.instrument.currency != self.base_currency for p in self.positions):
            raise ValueError("Mixed currencies require the future FX valuation pipeline.")
        return self

    @property
    def snapshot_id(self):
        body = self.model_dump(mode="json")
        body["positions"] = sorted(body["positions"], key=lambda p: p["instrument"]["instrument_id"])
        return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Quote(FrozenRecord):
    instrument_id: str
    price: PositiveDecimal
    currency: Currency
    as_of: datetime
    source: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def timestamp(self):
        if self.as_of.utcoffset() is None:
            raise ValueError("Quote time must include a timezone.")
        return self


class ValuedPosition(FrozenRecord):
    instrument_id: str
    quantity: PositiveDecimal
    market_value: Annotated[Decimal, Field(gt=0, le=Decimal("1e30"), allow_inf_nan=False)]
    weight: Weight


class ValuationSnapshot(FrozenRecord):
    holdings_snapshot_id: str
    base_currency: Currency
    positions: tuple[ValuedPosition, ...]
    quotes: tuple[Quote, ...]
    cash: NonNegativeDecimal
    total_value: Annotated[Decimal, Field(gt=0, le=Decimal("1e32"), allow_inf_nan=False)]
    cash_weight: Weight

    @property
    def valuation_id(self):
        body = self.model_dump(mode="json")
        return sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def value_holdings(snapshot: HoldingsSnapshot, quotes: tuple[Quote, ...]) -> ValuationSnapshot:
    """Join quotes by identity, never position; preserve cash and quote provenance."""
    quote_map = {q.instrument_id: q for q in quotes}
    expected = {p.instrument.instrument_id for p in snapshot.positions}
    if len(quote_map) != len(quotes) or set(quote_map) != expected:
        raise ValueError("Provide exactly one quote for every held instrument, with no extras.")
    positions = sorted(snapshot.positions, key=lambda p: p.instrument.instrument_id)
    values = []
    for position in positions:
        instrument = position.instrument
        quote = quote_map[instrument.instrument_id]
        if quote.currency != instrument.currency:
            raise ValueError("Quote currency does not match the instrument.")
        values.append(position.quantity * quote.price * instrument.price_multiplier)
    total = sum(values, snapshot.cash)
    return ValuationSnapshot(
        holdings_snapshot_id=snapshot.snapshot_id, base_currency=snapshot.base_currency,
        positions=tuple(ValuedPosition(instrument_id=p.instrument.instrument_id,
            quantity=p.quantity, market_value=v, weight=v / total) for p, v in zip(positions, values)),
        quotes=tuple(quote_map[p.instrument.instrument_id] for p in positions),
        cash=snapshot.cash, total_value=total, cash_weight=snapshot.cash / total,
    )
