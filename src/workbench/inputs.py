"""Parse the workbench's explicit holdings and historical-close CSV contracts."""
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import StringIO
import re

import pandas as pd
from pydantic import TypeAdapter, ValidationError

from src.domain.portfolio import Currency, HoldingsSnapshot, Instrument, Position, PositiveDecimal

HOLDINGS_HEADER = "exchange,ticker,asset_type,currency,quantity"
PRICES_HEADER = "date,exchange,ticker,currency,close"
MARKET = {"XNAS": "USD", "XNYS": "USD", "ARCX": "USD", "XASX": "AUD"}
MAX_SESSIONS = 2500
MIN_SESSIONS = 253
MAX_HOLDINGS_BYTES = 64 * 1024
MAX_PRICES_BYTES = 6 * 1024 * 1024
POSITIVE_DECIMAL = TypeAdapter(PositiveDecimal)
SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,15}")
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class ImportIssue(ValueError):
    """An issue users can fix in the named input file."""


def _rows(content, header, max_bytes, max_rows, *, field_limit=64):
    if len(content) > max_bytes:
        raise ImportIssue(f"File exceeds the {max_bytes:,}-byte limit.")
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportIssue("Save the CSV as UTF-8.") from exc
    reader = csv.reader(StringIO(csv_text, newline=""), strict=True)
    fields = header.split(",")
    try:
        actual = next(reader, [])
        actual = [value.strip().lower() for value in actual]
        if len(actual) != len(fields) or set(actual) != set(fields):
            raise ImportIssue(f"Expected these CSV headers: {header}.")
        count = 0
        while True:
            line = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                break
            if not row:
                continue
            count += 1
            if count > max_rows:
                raise ImportIssue(f"File exceeds the {max_rows:,}-row limit.")
            if len(row) != len(fields) or any(len(value) > field_limit for value in row):
                raise ImportIssue(f"Line {line}: wrong number of columns or field longer than {field_limit} characters.")
            yield line, dict(zip(actual, (value.strip() for value in row)))
        if not count:
            raise ImportIssue("The CSV has a header but no data rows.")
    except csv.Error as exc:
        raise ImportIssue(f"Line {reader.line_num}: malformed CSV.") from exc


def _instrument_id(row):
    exchange, symbol = row["exchange"].upper(), row["ticker"].upper()
    if exchange not in MARKET:
        raise ValueError("Exchange must be XNAS, XNYS, ARCX or XASX.")
    if not SYMBOL.fullmatch(symbol):
        raise ValueError("Ticker must contain 1–16 letters, digits, dots or dashes.")
    if row["currency"].upper() != MARKET[exchange]:
        raise ValueError(f"Prices and holdings on {exchange} must use {MARKET[exchange]}.")
    return f"{exchange}:{symbol}"


def _decimal(value):
    if len(value) > 48 or not NUMBER.fullmatch(value):
        raise ValueError("Use a decimal number with a period and no currency symbol or separator.")
    return Decimal(value)


def parse_holdings(content: bytes, cash: str, currency: Currency, confirmed_at: datetime) -> HoldingsSnapshot:
    positions = {}
    for line, row in _rows(content, HOLDINGS_HEADER, MAX_HOLDINGS_BYTES, 50):
        try:
            key = _instrument_id(row)
            exchange, ticker = key.split(":", maxsplit=1)
            if key in positions:
                raise ValueError(f"Duplicate holding {key}. Consolidate the quantities before importing.")
            if MARKET[exchange] != currency:
                raise ValueError(f"{key} uses {MARKET[exchange]}. Select a single-currency portfolio.")
            positions[key] = Position(
                instrument=Instrument(
                    instrument_id=key, ticker=ticker, exchange=exchange,
                    currency=currency, asset_type=row["asset_type"].lower(),
                    provider_symbol=ticker + (".AX" if exchange == "XASX" else ""),
                ),
                quantity=_decimal(row["quantity"]),
                source_rows=(line,),
            )
        except ValidationError as exc:
            raise ImportIssue(f"Holdings line {line}: use a positive quantity and asset type share or etf.") from exc
        except (ValueError, InvalidOperation) as exc:
            raise ImportIssue(f"Holdings line {line}: {exc}") from exc
    try:
        return HoldingsSnapshot(
            positions=tuple(positions[k] for k in sorted(positions)), cash=_decimal(cash),
            base_currency=currency, source="csv", confirmed_at=confirmed_at,
        )
    except (ValueError, InvalidOperation) as exc:
        raise ImportIssue("Enter a valid non-negative cash balance for the selected currency.") from exc


def parse_prices(content: bytes, holdings: HoldingsSnapshot) -> tuple[dict[str, dict[date, Decimal]], str]:
    closes = {position.instrument.instrument_id: {} for position in holdings.positions}
    for line, row in _rows(content, PRICES_HEADER, MAX_PRICES_BYTES, MAX_SESSIONS * len(closes)):
        try:
            key = _instrument_id(row)
            if key not in closes:
                raise ValueError(f"{key} is absent from the holdings file.")
            if not ISO_DATE.fullmatch(row["date"]):
                raise ValueError("Use YYYY-MM-DD for the session date.")
            session = date.fromisoformat(row["date"])
            if session < date(1900, 1, 1) or session > datetime.now(timezone.utc).date():
                raise ValueError("Session date must be between 1900-01-01 and today.")
            if session in closes[key]:
                raise ValueError(f"Duplicate close for {key} on {session}.")
            if len(closes[key]) == MAX_SESSIONS:
                raise ValueError(f"Provide at most {MAX_SESSIONS:,} sessions per instrument.")
            closes[key][session] = POSITIVE_DECIMAL.validate_python(_decimal(row["close"]))
        except ValidationError as exc:
            raise ImportIssue(f"Prices line {line}: close must be a finite, positive decimal within supported limits.") from exc
        except (ValueError, InvalidOperation) as exc:
            raise ImportIssue(f"Prices line {line}: {exc}") from exc

    first_key = next(iter(closes))
    calendar = set(closes[first_key])
    for key, series in closes.items():
        missing = sorted(calendar - series.keys())
        extra = sorted(series.keys() - calendar)
        if missing or extra:
            mismatch = (missing or extra)[0]
            raise ImportIssue(f"Session dates differ for {first_key} and {key}, first detected on {mismatch}. Use complete matching series.")
    if len(calendar) < MIN_SESSIONS:
        raise ImportIssue(f"Provide at least {MIN_SESSIONS} closing dates for each holding.")
    digest = sha256()
    for key, records in sorted(closes.items()):
        for session, close in sorted(records.items()):
            # Remove decimal scale formatting without context-dependent rounding.
            canonical_close = format(close, "f")
            if "." in canonical_close:
                canonical_close = canonical_close.rstrip("0").rstrip(".")
            digest.update(f"{key},{session},{canonical_close}\n".encode())
    return closes, digest.hexdigest()


def price_frame(closes: dict[str, dict[date, Decimal]]) -> pd.DataFrame:
    """Convert to float at the analytics boundary, after validating the exact prices."""
    return pd.DataFrame(closes, dtype=float).sort_index().sort_index(axis=1)
