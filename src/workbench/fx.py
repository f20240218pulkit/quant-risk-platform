"""AUD/USD mixed-currency review using explicit, aligned price and FX observations."""
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256

import pandas as pd
from pydantic import TypeAdapter

from src.core.validation import validate_returns
from src.core.var_engine import run_risk_suite
from src.domain.portfolio import NonNegativeDecimal, PositiveDecimal
from src.workbench.inputs import (
    HOLDINGS_HEADER, MAX_HOLDINGS_BYTES, MAX_SESSIONS, ImportIssue,
    _decimal, _instrument_id, _rows, parse_holdings, parse_prices, price_frame,
)
from src.workbench.review import _summary

FX_HEADER = "date,aud_per_usd"


def mixed_review(holdings_csv, prices_csv, fx_csv, cash_aud, cash_usd, base):
    if base not in {"AUD", "USD"}:
        raise ImportIssue("Select USD or AUD as the base currency.")
    currencies = {"AUD": [], "USD": []}
    seen = set()
    for line, row in _rows(holdings_csv, HOLDINGS_HEADER, MAX_HOLDINGS_BYTES, 50):
        try:
            key = _instrument_id(row)
            if key in seen:
                raise ValueError("Duplicate holding.")
            seen.add(key)
            currency = row["currency"].upper()
            currencies[currency].append(",".join(row[column] for column in HOLDINGS_HEADER.split(",")))
        except ValueError as exc:
            raise ImportIssue(f"Holdings line {line}: {exc}") from exc
    cash_type = TypeAdapter(NonNegativeDecimal)
    try:
        cash = {"AUD": cash_type.validate_python(_decimal(cash_aud)),
                "USD": cash_type.validate_python(_decimal(cash_usd))}
    except ValueError as exc:
        raise ImportIssue("Both cash balances must be non-negative decimal amounts.") from exc
    snapshots = {
        currency: parse_holdings(("\n".join([HOLDINGS_HEADER, *rows]) + "\n").encode(),
                                 str(cash[currency]), currency, datetime.now(timezone.utc))
        for currency, rows in currencies.items() if rows
    }
    # Price validation only needs the combined position IDs. No mixed-currency
    # holdings snapshot or native-currency valuation is manufactured here.
    from types import SimpleNamespace
    positions = tuple(p for s in snapshots.values() for p in s.positions)
    raw, price_id = parse_prices(prices_csv, SimpleNamespace(positions=positions))
    prices = price_frame(raw)
    factors = {}
    rate_type = TypeAdapter(PositiveDecimal)
    sessions = {str(session) for session in prices.index}
    for line, row in _rows(fx_csv, FX_HEADER, 256 * 1024, MAX_SESSIONS):
        session = row["date"]
        if session not in sessions or session in factors:
            raise ImportIssue(f"FX line {line}: unexpected or duplicated session {session}.")
        try:
            rate = rate_type.validate_python(_decimal(row["aud_per_usd"]))
            if not Decimal("0.1") <= rate <= Decimal("10"):
                raise ValueError("AUD per USD must be between 0.1 and 10.")
            factors[session] = rate
        except ValueError as exc:
            raise ImportIssue(f"FX line {line}: {exc}") from exc
    if factors.keys() != sessions:
        raise ImportIssue("Supply one FX rate for every closing-price session.")
    fx_id = sha256("".join(f"{d},{format(r.normalize(), 'f')}\n" for d, r in sorted(factors.items())).encode()).hexdigest()
    pivot = prices.index[-1]
    rate = factors[str(pivot)]
    conversion = {"USD": Decimal(1) if base == "USD" else rate,
                  "AUD": Decimal(1) if base == "AUD" else Decimal(1) / rate}
    aud_per_usd = pd.Series([float(factors[str(day)]) for day in prices.index], index=prices.index)
    foreign_currency = "USD" if base == "AUD" else "AUD"
    foreign_factor = aud_per_usd if base == "AUD" else 1 / aud_per_usd
    panel = prices.copy()
    values = {}
    for p in positions:
        key = p.instrument.instrument_id
        currency = p.instrument.currency
        values[key] = p.quantity * raw[key][pivot] * conversion[currency]
        if currency == foreign_currency:
            panel[key] *= foreign_factor
    for currency in cash:
        if cash[currency]:
            key = f"Cash {currency}"
            values[key] = cash[currency] * conversion[currency]
            panel[key] = foreign_factor if currency == foreign_currency else 1.0
    total = sum(values.values(), Decimal(0))
    weights = pd.Series({k: float(v / total) for k, v in values.items()})
    returns = validate_returns(panel.pct_change(fill_method=None).iloc[1:], 252)
    path = panel.div(panel.iloc[0]).dot(weights) * 100
    return {"base": base, "total": str(total), "as_of": str(pivot), "rate": str(rate),
            "values": {k: str(v) for k, v in values.items()}, "price_dataset_id": price_id, "fx_dataset_id": fx_id,
            "risk": run_risk_suite(returns.dot(weights), float(total), .95),
            "replay": _summary(path), "weights": weights.to_dict(), "path": path}
