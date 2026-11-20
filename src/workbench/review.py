"""Run one dated review from a holdings snapshot and a matching close panel."""
from dataclasses import dataclass, replace
from datetime import datetime, time, timezone
from decimal import Decimal

import numpy as np
import pandas as pd

from src.core.validation import validate_returns
from src.core.var_engine import run_risk_suite
from src.domain.portfolio import HoldingsSnapshot, Quote, ValuationSnapshot, value_holdings
from src.workbench.inputs import parse_holdings, parse_prices, price_frame

REPORT_VERSION = "portfolio-review-1"


@dataclass(frozen=True)
class PreparedReview:
    holdings: HoldingsSnapshot
    valuation: ValuationSnapshot
    closes: pd.DataFrame
    prices_id: str
    demo: bool


def prepare_review(holdings_csv: bytes, close_csv: bytes, cash: str, currency, *, demo=False):
    now = datetime.now(timezone.utc)
    holdings = parse_holdings(holdings_csv, cash, currency, now)
    source = "synthetic demo" if demo else "user-supplied historical closes"
    raw, prices_id = parse_prices(close_csv, holdings)
    closes = price_frame(raw)
    session = closes.index[-1]
    # The row identifies the exchange session date. This datetime marks that date
    # for the existing quote contract and does not claim a measured quote time.
    date_marker = datetime.combine(session, time.min, timezone.utc)
    quotes = tuple(
        Quote(instrument_id=key, price=rows[session], currency=currency, as_of=date_marker, source=source)
        for key, rows in raw.items()
    )
    return PreparedReview(holdings, value_holdings(holdings, quotes), closes, prices_id, demo)


def confirm_review(draft: PreparedReview) -> PreparedReview:
    holdings = draft.holdings.model_copy(update={"confirmed_at": datetime.now(timezone.utc)})
    return replace(draft, holdings=holdings, valuation=value_holdings(holdings, draft.valuation.quotes))


def _summary(path):
    peak = path.cummax()
    return {
        "terminal_return": float(path.iloc[-1] / path.iloc[0] - 1),
        "max_drawdown": float((path / peak - 1).min()),
    }


def review_portfolio(prepared: PreparedReview) -> tuple[dict, pd.DataFrame]:
    valuation = prepared.valuation
    closes = prepared.closes
    weights = pd.Series({p.instrument_id: float(p.weight) for p in valuation.positions})
    cash_weight = float(valuation.cash_weight)
    returns = validate_returns(closes.pct_change(fill_method=None).iloc[1:], min_observations=252)
    portfolio_returns = returns.dot(weights)
    total = float(valuation.total_value)
    risk = run_risk_suite(portfolio_returns, total, 0.95)

    growth = closes.div(closes.iloc[0])
    benchmark_weights = pd.Series((1 - cash_weight) / len(weights), index=weights.index)
    paths = pd.DataFrame({
        "Portfolio exposure": 100 * (growth.dot(weights) + cash_weight),
        "Equal-weight benchmark": 100 * (growth.dot(benchmark_weights) + cash_weight),
    })
    if not np.isfinite(paths.to_numpy()).all():
        raise ValueError("The submitted price ranges could not be compared.")
    report = {
        "format": REPORT_VERSION,
        "source": "synthetic demo" if prepared.demo else "user-supplied closes",
        "holdings_id": prepared.holdings.snapshot_id,
        "valuation_id": valuation.valuation_id,
        "price_dataset_id": prepared.prices_id,
        "session_start": str(closes.index[0]),
        "session_end": str(closes.index[-1]),
        "return_observations": len(returns),
        "confidence": 0.95,
        "risk_horizon_sessions": 1,
        "valuation": valuation.model_dump(mode="json"),
        "holdings": prepared.holdings.model_dump(mode="json"),
        "risk": risk,
        "comparison": {name: _summary(paths[name]) for name in paths.columns},
        "replay": [
            {"session": str(session), **row.to_dict()} for session, row in paths.iterrows()
        ],
        "assumptions": [
            "VaR and expected shortfall apply valuation-date exposures to prior daily returns.",
            "Replay starts at 100 using valuation-date weights, then holds quantities fixed.",
            "The benchmark gives the same invested sleeve equal initial weights and preserves cash.",
            "Cash earns zero. This replay excludes fills, fees, slippage and corporate-action accounting.",
            "Dates are user-supplied sessions. The valuation quote timestamp is a session-date marker.",
        ],
    }
    return report, paths


def shock_position(valuation: ValuationSnapshot, instrument_id: str, price_change: Decimal) -> dict:
    if not price_change.is_finite() or not Decimal("-1") <= price_change <= Decimal("1"):
        raise ValueError("Shock must be between -100% and +100%.")
    for position in valuation.positions:
        if position.instrument_id == instrument_id:
            pnl = position.market_value * price_change
            return {
                "instrument_id": instrument_id,
                "assumed_price_change": str(price_change),
                "pnl": str(pnl),
                "shocked_equity": str(valuation.total_value + pnl),
                "portfolio_change": str(pnl / valuation.total_value),
            }
    raise ValueError("Choose an instrument in the confirmed portfolio.")
