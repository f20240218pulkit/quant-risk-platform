"""Fixed-holdings historical replay; unavailable data is never zero risk."""
import numpy as np
import pandas as pd

from src.core.data_loader import fetch_portfolio_data
from src.core.validation import DataQualityError, allocation, clean_tickers

# End dates are inclusive here, unlike the provider API.
CRISIS_SCENARIOS = {
    "2008_GFC": {"name": "2008 Great Financial Crisis", "start": "2008-09-01", "end": "2009-03-09"},
    "2020_COVID": {"name": "2020 COVID-19 Liquidity Shock", "start": "2020-02-19", "end": "2020-03-23"},
    "2022_INFLATION": {"name": "2022 Tech & Rate Hike Sell-Off", "start": "2022-01-03", "end": "2022-12-30"},
}


def replay_prices(prices, weights, portfolio_value=100000.0, cash_weight=0.0):
    weights = allocation(weights, prices.shape[1], cash_weight)
    values = prices.to_numpy(dtype=float)
    if len(values) < 2 or not np.isfinite(values).all() or (values <= 0).any():
        raise DataQualityError("Crisis replay needs complete, positive prices.")
    if not np.isfinite(portfolio_value) or portfolio_value <= 0:
        raise ValueError("Portfolio value must be finite and positive.")
    indexed = values / values[0] @ weights + cash_weight
    drawdowns = indexed / np.maximum.accumulate(indexed) - 1
    max_dd = float(drawdowns.min())
    trough = float(indexed.min())
    return {
        "max_drawdown_pct": max_dd,
        "dollar_loss": float(portfolio_value * abs(max_dd)),
        "loss_equivalent_definition": "initial_value_times_max_drawdown",
        "start_to_trough_return_pct": trough - 1,
        "start_to_trough_loss": float(portfolio_value * (1 - trough)),
        "estimated_portfolio_bottom": float(portfolio_value * trough),
        "terminal_return_pct": float(indexed[-1] - 1),
        "terminal_value": float(portfolio_value * indexed[-1]),
        "observation_start": str(prices.index[0].date()),
        "observation_end": str(prices.index[-1].date()),
        "observations": len(prices), "cash_weight": cash_weight,
        "rebalancing": "fixed_holdings",
    }


def run_stress_test(tickers, weights, portfolio_value=100000.0, cash_weight=0.0):
    tickers = clean_tickers(tickers)
    allocation(weights, len(tickers), cash_weight)
    results = {}
    for key, scenario in CRISIS_SCENARIOS.items():
        base = {"scenario_name": scenario["name"], "requested_start": scenario["start"], "requested_end": scenario["end"]}
        try:
            exclusive_end = (pd.Timestamp(scenario["end"]) + pd.Timedelta(days=1)).date().isoformat()
            prices, _ = fetch_portfolio_data(tickers, scenario["start"], exclusive_end)
            # Reject obviously truncated histories, while allowing boundary holidays.
            if ((prices.index[0].date() - pd.Timestamp(scenario["start"]).date()).days > 7
                or (pd.Timestamp(scenario["end"]).date() - prices.index[-1].date()).days > 7):
                raise DataQualityError("History does not span the requested crisis window.")
            results[key] = {**base, "status": "Success", **replay_prices(prices, weights, portfolio_value, cash_weight)}
        except DataQualityError as exc:
            results[key] = {**base, "status": "Incomplete Data", "note": str(exc),
                "max_drawdown_pct": None, "dollar_loss": None}
        except Exception:
            results[key] = {**base, "status": "Error", "note": "Crisis data could not be retrieved or processed.",
                "max_drawdown_pct": None, "dollar_loss": None}
    return results
