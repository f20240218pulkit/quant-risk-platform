import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"

def test_risk_api_endpoint():
    payload = {
        "tickers": ["AAPL", "MSFT"],
        "weights": [0.5, 0.5],
        "portfolio_value": 100000.0,
        "confidence_level": 0.95
    }
    response = client.post("/api/v1/risk", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "parametric_var" in data["data"]

def test_monte_carlo_api_endpoint():
    payload = {
        "tickers": ["AAPL", "MSFT"],
        "weights": [0.5, 0.5],
        "portfolio_value": 100000.0,
        "days": 5,
        "n_simulations": 500,
        "confidence_level": 0.95
    }
    response = client.post("/api/v1/monte-carlo", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "trajectories" in data["data"]