"""Explicit adjusted-price download and strict observation validation."""
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from src.core.validation import DataQualityError, clean_tickers


def extract_prices(raw_data, tickers):
    """Handle yfinance's single/multiple-symbol shape without changing order."""
    if raw_data is None or raw_data.empty:
        raise DataQualityError("The provider returned no price observations.")
    if isinstance(raw_data.columns, pd.MultiIndex):
        if "Close" not in raw_data.columns.get_level_values(0):
            raise DataQualityError("The provider did not return adjusted Close prices.")
        prices = raw_data["Close"]
    elif "Close" in raw_data.columns and len(tickers) == 1:
        prices = raw_data["Close"].to_frame(name=tickers[0])
    else:
        raise DataQualityError("Unexpected provider price schema.")
    if isinstance(prices, pd.Series):
        prices = prices.to_frame(name=tickers[0])
    return prices


def validate_prices(prices, tickers, min_observations=3):
    tickers = clean_tickers(tickers)
    if prices.columns.has_duplicates or prices.index.has_duplicates or not prices.index.is_monotonic_increasing:
        raise DataQualityError("Price symbols and dates must be unique and ordered.")
    missing = [ticker for ticker in tickers if ticker not in prices.columns]
    if missing:
        raise DataQualityError("Missing price history: " + ", ".join(missing))
    prices = prices.loc[:, tickers].copy()
    if len(prices) < min_observations:
        raise DataQualityError(f"Require at least {min_observations} price observations.")
    values = prices.to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise DataQualityError("Price history contains missing, non-finite, or non-positive values; no filling was applied.")
    return prices


def fetch_portfolio_data(tickers, start_date="2020-01-01", end_date: Optional[str] = None):
    """End date is exclusive. No implicit filling or silently shortened history.

    This first release requires a complete shared calendar. Cross-market calendar
    reconciliation and bounded stale observations belong to the FX milestone.
    """
    tickers = clean_tickers(tickers)
    raw = yf.download(tickers=tickers, start=start_date, end=end_date,
                      auto_adjust=True, progress=False)
    prices = validate_prices(extract_prices(raw, tickers), tickers)
    returns = prices.pct_change(fill_method=None).iloc[1:]
    return prices, returns
