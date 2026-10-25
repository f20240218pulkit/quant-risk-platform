"""No provider access is permitted in normal test runs."""
import numpy as np
import pandas as pd
import pytest
import yfinance as yf


@pytest.fixture(autouse=True)
def no_market_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Mock the market-data boundary; normal tests must not access Yahoo.")
    monkeypatch.setattr(yf, "download", blocked)


@pytest.fixture
def market_returns():
    rng = np.random.default_rng(123)
    return pd.DataFrame(rng.normal([.0004, .0007], [.01, .02], (300, 2)),
        columns=["AAPL", "MSFT"], index=pd.bdate_range("2023-01-02", periods=300))


@pytest.fixture
def api_history(monkeypatch, market_returns):
    from src.api import main
    def fake(tickers, start_date=None, end_date=None):
        # Deliberately return the opposite column order to expose positional joins.
        frame = market_returns.loc[:, list(reversed(tickers))]
        prices = (1 + frame).cumprod() * 100
        return prices, frame
    monkeypatch.setattr(main, "fetch_portfolio_data", fake)
    return market_returns
