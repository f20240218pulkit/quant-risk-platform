import pytest
import numpy as np
import pandas as pd
from src.core.var_engine import calculate_parametric_var, calculate_historical_var, calculate_cvar
from src.core.monte_carlo import run_monte_carlo_simulation
from src.core.optimization import optimize_portfolio

@pytest.fixture
def sample_returns():
    """Generates synthetic portfolio daily return series for deterministic testing."""
    np.random.seed(42)
    dates = pd.date_range(start="2023-01-01", periods=100)
    returns_data = {
        "AAPL": np.random.normal(0.001, 0.02, 100),
        "MSFT": np.random.normal(0.0008, 0.015, 100)
    }
    return pd.DataFrame(returns_data, index=dates)

def test_parametric_var(sample_returns):
    portfolio_returns = sample_returns.mean(axis=1)
    res = calculate_parametric_var(portfolio_returns, portfolio_value=100000, confidence_level=0.95)
    
    # Changed < 0 to > 0 (and ensuring it's less than 100% loss)
    assert 0 < res["var_pct"] < 1, "VaR percentage should be a positive scalar between 0 and 1"
    assert res["var_dollar"] > 0, "VaR dollar loss should be a positive scalar"
    assert res["var_dollar"] < 100000, "VaR dollar loss cannot exceed total portfolio value"

def test_historical_var(sample_returns):
    portfolio_returns = sample_returns.mean(axis=1)
    res = calculate_historical_var(portfolio_returns, portfolio_value=100000, confidence_level=0.95)
    
    # Changed < 0 to > 0
    assert 0 < res["var_pct"] < 1
    assert res["var_dollar"] > 0
def test_cvar_expected_shortfall(sample_returns):
    portfolio_returns = sample_returns.mean(axis=1)
    h_res = calculate_historical_var(portfolio_returns, portfolio_value=100000, confidence_level=0.95)
    c_res = calculate_cvar(portfolio_returns, portfolio_value=100000, confidence_level=0.95)
    
    assert c_res["cvar_dollar"] >= h_res["var_dollar"], "CVaR loss must be greater than or equal to VaR loss"

def test_monte_carlo_simulation(sample_returns):
    weights = [0.5, 0.5]
    results = run_monte_carlo_simulation(
        returns=sample_returns,
        weights=weights,
        portfolio_value=100000,
        days=5,
        n_simulations=500,
        confidence_level=0.95
    )
    
    assert "trajectories" in results
    assert results["trajectories"].shape == (500, 6)  # 500 paths x 6 timesteps (day 0 to 5)
    assert results["mc_var_dollar"] > 0

def test_portfolio_optimization(sample_returns):
    results = optimize_portfolio(sample_returns, risk_free_rate=0.02)
    
    assert "max_sharpe" in results
    assert "min_variance" in results
    
    ms_weights = results["max_sharpe"]["weights"]
    assert pytest.approx(sum(ms_weights.values()), abs=1e-4) == 1.0, "Portfolio weights must sum to 1.0"