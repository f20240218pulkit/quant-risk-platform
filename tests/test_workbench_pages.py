from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception and not app.error


def page(function):
    return AppTest.from_string(
        f"from src.ui.workbench_pages import {function}\n{function}()", default_timeout=30
    ).run()


def test_research_and_currency_pages_generate_reports():
    app = page("research_page")
    app.checkbox[0].set_value(True)
    click(app, "Run research comparison")
    assert len(app.session_state["research_report"]["runs"]) == 10
    assert len(app.session_state["research_report"]["cost_sensitivity"]) == 3
    assert any(item.label == "Download experiment" for item in app.get("download_button"))

    app = page("currency_page")
    click(app, "Analyse currency exposure")
    assert app.session_state["fx_report"]["base"] == "AUD"
    assert "Cash USD" in app.session_state["fx_report"]["values"]
    assert any(item.label == "Download FX review" for item in app.get("download_button"))


def test_navigation_entry_and_advanced_review_and_session_saving():
    app = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=30).run()
    assert not app.exception
    click(app, "Preview sample")
    click(app, "Confirm and run review")
    click(app, "Run simulation and optimisation")
    assert app.session_state["extra_risk"]["simulation"]["n_simulations"] == 2000
    click(app, "Save review")
    assert any("saved for this browser session" in message.value for message in app.success)


def test_synthetic_broker_import_produces_reviewable_holdings():
    app = page("broker_page")
    click(app, "Load sample broker holdings")
    assert app.session_state["broker_snapshot"]["cash"] == {"USD": "2000"}
    assert any(item.label == "Download broker holdings CSV" for item in app.get("download_button"))
