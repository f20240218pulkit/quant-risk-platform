"""Exercise real UI -> API -> engine with deterministic provider fixtures."""
from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
import requests

from src.api.main import app
from src.ui.components.charts import plot_monte_carlo_fan_chart


def test_fan_chart_uses_full_population_bands():
    figure = plot_monte_carlo_fan_chart([[100, 500], [100, 600]], 100,
        {"p10": [100, 90], "p50": [100, 110], "p90": [100, 130]})
    assert list(figure.data[0].y) == [100, 130]
    assert list(figure.data[1].y) == [100, 90]
    assert list(figure.data[-1].y) == [100, 110]


def test_dashboard_runs_all_modules_and_preserves_cash(monkeypatch, api_history):
    client = TestClient(app)
    calls = []
    def post(url, json, **kwargs):
        calls.append(json)
        response = client.post('/' + url.split('/', 3)[3], json=json)
        return SimpleNamespace(ok=response.is_success, status_code=response.status_code, json=response.json)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", lambda *a, **kw: SimpleNamespace(ok=True, json=lambda: {"status": "online"}))
    monkeypatch.setattr("src.api.main.run_stress_test", lambda *a: {
        "test": {"status": "Success", "scenario_name": "Test crisis", "max_drawdown_pct": -.2, "dollar_loss": 20000}})
    at = AppTest.from_file(Path(__file__).resolve().parents[1] / "src/ui/app.py", default_timeout=30).run()
    assert not at.exception
    at.text_input[0].set_value("AAPL, MSFT")
    next(slider for slider in at.slider if slider.label == "Cash allocation · %").set_value(20)
    at.run()
    at.button[0].click().run()
    assert not at.exception
    assert not at.error
    assert len(at.tabs) == 4
    assert len(at.get("plotly_chart")) == 3
    assert all(body["cash_weight"] == .2 for body in calls)
    frame = at.dataframe[0].value
    assert frame["Allocation (%)"].sum() == 100
    assert frame.iloc[-1]["Asset"] == "Cash (USD)"
    # Inputs change without losing the original analysis snapshot.
    next(slider for slider in at.slider if slider.label == "Cash allocation · %").set_value(30)
    at.run()
    assert not at.exception
    assert any("inputs have changed" in item.value for item in at.info)
