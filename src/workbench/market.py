"""Opt-in personal-use market data. Verification uses provider metadata and labels."""
import hashlib
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pandas as pd
import yfinance as yf

from src.core.data_loader import validate_prices
from src.core.monte_carlo import compact_simulation, run_monte_carlo_simulation
from src.core.optimization import generate_efficient_frontier, optimize_portfolio
from src.core.stress_testing import CRISIS_SCENARIOS, replay_prices
from src.domain.portfolio import Quote, value_holdings
from src.workbench.inputs import ImportIssue, parse_holdings
from src.workbench.review import PreparedReview

EXCHANGES = {
    "XNAS": {"NMS", "NGM", "NCM", "NASDAQ", "NASDAQGS", "NASDAQGM", "NASDAQCM"},
    "XNYS": {"NYQ", "NYSE"},
    "ARCX": {"PCX", "NYSEARCA"},
    "XASX": {"ASX"},
}


def yahoo_history(position, start, end):
    instrument = position.instrument
    try:
        ticker = yf.Ticker(instrument.provider_symbol)
        history = ticker.history(start=str(start), end=str(end), auto_adjust=False, timeout=8)
        metadata = ticker.history_metadata
    except Exception as exc:
        raise ImportIssue(f"Provider could not return prices for {instrument.instrument_id}.") from exc
    exchange = str(metadata.get("exchangeName", "")).upper()
    asset_type = {"EQUITY": "share", "ETF": "etf"}.get(metadata.get("instrumentType"))
    if exchange not in EXCHANGES[instrument.exchange] or metadata.get("currency") != instrument.currency:
        raise ImportIssue(f"Provider could not confirm exchange and currency for {instrument.instrument_id}.")
    if asset_type != instrument.asset_type:
        raise ImportIssue(f"Provider could not confirm the declared asset type for {instrument.instrument_id}.")
    if history.empty or not {"Close", "Adj Close"}.issubset(history.columns):
        raise ImportIssue(f"Provider did not supply both valuation and adjusted prices for {instrument.instrument_id}.")
    return history.assign(session=history.index.date).set_index("session")


def aligned_history(holdings, start, end, get_history, min_observations):
    adjusted, raw = {}, {}
    for position in holdings.positions:
        key = position.instrument.instrument_id
        history = get_history(position, start, end)
        adjusted[key] = history["Adj Close"]
        raw[key] = history["Close"]
    frame = pd.DataFrame(adjusted).sort_index()
    frame = validate_prices(frame, list(adjusted), min_observations)
    return frame, raw


def prepare_market_review(holdings_csv, cash, currency, *, get_history=yahoo_history, today=None):
    now = datetime.now(timezone.utc)
    today = today or now.date()
    holdings = parse_holdings(holdings_csv, cash, currency, now)
    if len(holdings.positions) > 10:
        raise ImportIssue("Automatic pricing supports up to 10 holdings per review.")
    # Exclude the current UTC date to avoid taking a partial session as a close.
    frame, raw = aligned_history(holdings, today - timedelta(days=425), today, get_history, 253)
    session = frame.index[-1]
    age = (today - session).days
    if age < 1 or age > 7:
        raise ImportIssue(f"Latest completed close is {session}. Automatic mode requires a close within seven days.")
    quotes = tuple(
        Quote(instrument_id=key, price=Decimal(f"{series.loc[session]:.10f}"), currency=currency,
              as_of=datetime.combine(session, time.min, timezone.utc), source="Yahoo Finance daily close")
        for key, series in raw.items()
    )
    digest = hashlib.sha256(frame.to_csv(float_format="%.17g").encode()).hexdigest()
    return PreparedReview(holdings, value_holdings(holdings, quotes), frame, digest, False, "Yahoo Finance")


def extended_risk(prepared, days=10, paths=2000, seed=42):
    weights = {p.instrument_id: float(p.weight) for p in prepared.valuation.positions}
    returns = prepared.closes.pct_change(fill_method=None).iloc[1:]
    returns = returns.loc[:, list(weights)]
    cash = float(prepared.valuation.cash_weight)
    total = float(prepared.valuation.total_value)
    simulation = compact_simulation(run_monte_carlo_simulation(
        returns, list(weights.values()), total, days, paths, .95, seed, cash,
    ), max_paths=20)
    try:
        optimisation = optimize_portfolio(returns, cash_weight=cash)
        frontier = generate_efficient_frontier(returns, n_points=12, cash_weight=cash)
        optimiser_status = "Complete"
    except (ValueError, ArithmeticError):
        optimisation, frontier = {}, []
        optimiser_status = "Unavailable for this dataset"
    return {"simulation": simulation, "correlation": returns.corr(),
            "optimisation": optimisation, "frontier": frontier, "optimiser_status": optimiser_status}


def historical_crises(prepared, get_history=yahoo_history):
    weights = {p.instrument_id: float(p.weight) for p in prepared.valuation.positions}
    results = {}
    for scenario in CRISIS_SCENARIOS.values():
        start = date.fromisoformat(scenario["start"])
        end = date.fromisoformat(scenario["end"])
        try:
            prices, _ = aligned_history(prepared.holdings, start, end + timedelta(days=1), get_history, 3)
            if (prices.index[0] - start).days > 7 or (end - prices.index[-1]).days > 7:
                raise ImportIssue("The source series does not cover the requested crisis window.")
            replay = replay_prices(prices.set_axis(pd.to_datetime(prices.index)),
                                   [weights[k] for k in prices.columns],
                                   float(prepared.valuation.total_value), float(prepared.valuation.cash_weight))
            results[scenario["name"]] = replay
        except (ValueError, KeyError):
            results[scenario["name"]] = {"status": "Unavailable", "reason": "Missing or invalid crisis coverage"}
    return results
