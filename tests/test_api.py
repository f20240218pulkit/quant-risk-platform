from fastapi.testclient import TestClient
import numpy as np
import pytest

from src.api.main import app
from src.core.var_engine import run_risk_suite

client = TestClient(app)
BASE = {"tickers": ["AAPL", "MSFT"], "weights": [.8, .2], "portfolio_value": 100000.0}


def test_health_check():
    assert client.get("/").json()["status"] == "online"


def test_risk_matches_labelled_allocation(api_history):
    response = client.post("/api/v1/risk", json=BASE)
    assert response.status_code == 200
    expected = run_risk_suite(api_history.dot([.8, .2]), 100000, .95)
    assert response.json()["data"] == expected
    assert response.json()["metadata"]["observations"] == 300


def test_order_invariance(api_history):
    first = client.post("/api/v1/risk", json=BASE).json()["data"]
    second = client.post("/api/v1/risk", json={**BASE, "tickers": ["MSFT", "AAPL"], "weights": [.2, .8]}).json()["data"]
    for name in first:
        assert first[name] == pytest.approx(second[name], rel=1e-12, abs=1e-12)


def test_cash_reduces_risk_without_renormalising(api_history):
    full = client.post("/api/v1/risk", json=BASE).json()["data"]
    cash = client.post("/api/v1/risk", json={**BASE, "cash_weight": .2}).json()["data"]
    for name, metrics in full.items():
        for key, value in metrics.items():
            assert cash[name][key] == pytest.approx(value * .8)


@pytest.mark.parametrize("change", [
    {"weights": [0, 0]}, {"weights": [1]}, {"weights": [-1, 2]},
    {"tickers": ["AAPL", " aapl "]}, {"start_date": "yesterday"},
    {"portfolio_value": -1}, {"cash_weight": 1.1}, {"tickers": []},
])
def test_invalid_input_never_fetches_data(change):
    assert client.post("/api/v1/risk", json={**BASE, **change}).status_code == 422


def test_simulation_metrics_use_all_paths_but_response_is_bounded(api_history):
    response = client.post("/api/v1/monte-carlo", json={**BASE, "days": 10, "n_simulations": 10000})
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["n_simulations"] == 10000
    assert len(result["trajectories"]) == 100
    assert len(result["percentiles"]["p50"]) == 11
    assert len(response.content) < 1_000_000
    assert np.isfinite(result["mc_var_dollar"])


def test_workload_rejected_before_market_fetch():
    response = client.post("/api/v1/monte-carlo", json={**BASE, "days": 252, "n_simulations": 50000})
    assert response.status_code == 422


def test_insufficient_history(monkeypatch, market_returns):
    monkeypatch.setattr("src.api.main.fetch_portfolio_data", lambda *a, **kw: (None, market_returns.iloc[:10]))
    response = client.post("/api/v1/risk", json=BASE)
    assert response.status_code == 422
    assert "252" in response.json()["detail"]


def test_provider_failure_does_not_leak_exception(monkeypatch):
    def fail(*a, **kw):
        raise RuntimeError("private provider detail")
    monkeypatch.setattr("src.api.main.fetch_portfolio_data", fail)
    response = client.post("/api/v1/risk", json=BASE)
    assert response.status_code == 502
    assert "private" not in response.text


def test_optimisation_fixed_cash(api_history):
    response = client.post("/api/v1/optimize", json={"tickers": ["AAPL", "MSFT"], "cash_weight": .2})
    assert response.status_code == 200
    for portfolio in response.json()["data"]["portfolios"].values():
        assert sum(portfolio["weights"].values()) == pytest.approx(.8)
        assert portfolio["cash_weight"] == .2
