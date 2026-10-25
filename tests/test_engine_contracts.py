from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.core.data_loader import fetch_portfolio_data, validate_prices
from src.core.monte_carlo import compact_simulation, run_monte_carlo_simulation
from src.core.optimization import OptimizationError, optimize_portfolio
from src.core.stress_testing import replay_prices, run_stress_test
from src.core.validation import DataQualityError, allocation
from src.core.var_engine import calculate_historical_var, calculate_cvar


def test_known_historical_quantile_and_tail():
    values = np.array([-.1, -.05, 0, .05, .1])
    assert calculate_historical_var(values, 1000, .8)["var_dollar"] == pytest.approx(60)
    assert calculate_cvar(values, 1000, .8)["cvar_dollar"] == pytest.approx(100)


@pytest.mark.parametrize("values", [[], [0.01], [0, np.inf], [0, np.nan]])
def test_invalid_risk_series(values):
    with pytest.raises(ValueError):
        calculate_historical_var(values)


def test_cash_allocation():
    assert allocation([4, 1], 2, .2) == pytest.approx([.64, .16])


def test_zero_volatility_has_no_random_artificial_risk():
    returns = pd.DataFrame({"A": [.01] * 300})
    result = run_monte_carlo_simulation(returns, [1], 1000, 5, 500, cash_weight=.2)
    expected = 1000 * (.8 * 1.01 ** 5 + .2)
    assert result["trajectories"][:, -1] == pytest.approx(np.full(500, expected))


def test_seed_is_local_and_results_reproducible(market_returns):
    np.random.seed(99)
    expected = np.random.random(3)
    np.random.seed(99)
    a = run_monte_carlo_simulation(market_returns, [.8, .2], days=5, n_simulations=500)
    assert np.random.random(3) == pytest.approx(expected)
    b = run_monte_carlo_simulation(market_returns, [.8, .2], days=5, n_simulations=500)
    assert np.array_equal(a["trajectories"], b["trajectories"])
    compact = compact_simulation(a)
    assert compact["mc_var_dollar"] == a["mc_var_dollar"]
    assert compact["percentiles"] == a["percentiles"]


def test_singular_correlated_assets_supported():
    values = [.01, -.02, .03, -.01] * 75
    frame = pd.DataFrame({"A": values, "B": values})
    result = run_monte_carlo_simulation(frame, [.5, .5], days=5, n_simulations=500)
    assert np.isfinite(result["trajectories"]).all()
    assert (result["trajectories"] > 0).all()


def test_failed_solver_is_not_an_allocation(monkeypatch, market_returns):
    monkeypatch.setattr("src.core.optimization.sco.minimize", lambda *a, **kw: SimpleNamespace(success=False, x=np.array([.5, .5])))
    with pytest.raises(OptimizationError):
        optimize_portfolio(market_returns)


def test_single_asset_optimisation(market_returns):
    output = optimize_portfolio(market_returns[["AAPL"]], cash_weight=.2)
    assert output["max_sharpe"]["weights"] == {"AAPL": .8}


@pytest.mark.parametrize("bad", [np.nan, np.inf, 0, -1])
def test_invalid_price_data_is_not_filled(bad):
    prices = pd.DataFrame({"A": [100., bad, 101.]})
    with pytest.raises(DataQualityError):
        validate_prices(prices, ["A"])


def test_download_explicit_adjustment_and_ticker_order(monkeypatch):
    calls = {}
    def fake(**kwargs):
        calls.update(kwargs)
        return pd.DataFrame({("Close", "MSFT"): [100, 110, 121], ("Close", "AAPL"): [10, 11, 12]})
    monkeypatch.setattr("src.core.data_loader.yf.download", fake)
    prices, returns = fetch_portfolio_data(["AAPL", "MSFT"])
    assert list(prices.columns) == ["AAPL", "MSFT"]
    assert list(returns.columns) == ["AAPL", "MSFT"]
    assert calls["auto_adjust"] is True


def test_stress_drawdown_is_distinct_from_start_to_trough():
    prices = pd.DataFrame({"A": [100, 200, 150]}, index=pd.date_range("2020-01-01", periods=3))
    result = replay_prices(prices, [1], 1000)
    assert result["max_drawdown_pct"] == -.25
    assert result["dollar_loss"] == 250
    assert result["estimated_portfolio_bottom"] == 1000
    assert result["start_to_trough_loss"] == 0
    assert result["terminal_value"] == 1500


def test_missing_stress_history_is_unavailable_not_zero(monkeypatch):
    def missing(*a, **kw):
        raise DataQualityError("Asset not listed during this period.")
    monkeypatch.setattr("src.core.stress_testing.fetch_portfolio_data", missing)
    output = run_stress_test(["AAPL"], [1])
    for scenario in output.values():
        assert scenario["status"] == "Incomplete Data"
        assert scenario["max_drawdown_pct"] is None
        assert scenario["dollar_loss"] is None


def test_stress_includes_scenario_end_date(monkeypatch):
    calls = []
    def fake(tickers, start, end):
        calls.append(end)
        frame = pd.DataFrame({"AAPL": [100, 90, 95]}, index=pd.to_datetime([start, pd.Timestamp(start) + pd.Timedelta(days=1), pd.Timestamp(end) - pd.Timedelta(days=1)]))
        return frame, None
    monkeypatch.setattr("src.core.stress_testing.fetch_portfolio_data", fake)
    output = run_stress_test(["AAPL"], [1])
    assert calls == ["2009-03-10", "2020-03-24", "2022-12-31"]
    assert all(s["status"] == "Success" for s in output.values())


def test_known_parametric_var():
    from src.core.var_engine import calculate_parametric_var
    assert calculate_parametric_var([-.1, .1], 1000, .95)["var_dollar"] == pytest.approx(164.48536269514722)


def test_multiday_simulation_drifts_weights_instead_of_daily_rebalancing():
    returns = pd.DataFrame({"A": [.01] * 300, "B": [-.01] * 300})
    output = run_monte_carlo_simulation(returns, [.5, .5], 1000, days=10, n_simulations=500)
    expected = 1000 * (.5 * 1.01 ** 10 + .5 * .99 ** 10)
    assert output["trajectories"][:, -1] == pytest.approx(np.full(500, expected))
    assert expected > 1000  # Daily rebalanced 50/50 would remain exactly 1000.
