from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.workbench.demo import HOLDINGS_SAMPLE, demo_closes
from src.workbench.inputs import HOLDINGS_HEADER, PRICES_HEADER, ImportIssue
from src.workbench.review import confirm_review, prepare_review, review_portfolio, shock_position


def test_review_matches_hand_calculated_cash_benchmark_and_shock():
    holdings = (HOLDINGS_HEADER + "\nXNAS,AAA,share,USD,5\nARCX,BBB,etf,USD,5\n").encode()
    lines = [PRICES_HEADER]
    for i in range(253):
        session = date(2024, 1, 1) + timedelta(days=i)
        a = 100 if i == 0 else (200 if i == 252 else 120)
        lines += [f"{session},XNAS,AAA,USD,{a}", f"{session},ARCX,BBB,USD,100"]
    closes = ("\n".join(lines) + "\n").encode()
    draft = prepare_review(holdings, closes, "500", "USD")
    review = confirm_review(draft)
    report, paths = review_portfolio(review)
    assert review.holdings.confirmed_at >= draft.holdings.confirmed_at
    assert report["source"] == "user-supplied closes"
    assert report["valuation"]["total_value"] == "2000"
    assert report["valuation"]["cash_weight"] == "0.25"
    assert report["return_observations"] == 252
    assert list(paths.iloc[0]) == pytest.approx([100, 100])
    assert list(paths.iloc[-1]) == pytest.approx([150, 137.5])
    result = shock_position(review.valuation, "XNAS:AAA", Decimal("-.15"))
    assert Decimal(result["pnl"]) == -150
    assert Decimal(result["shocked_equity"]) == 1850
    assert Decimal(result["portfolio_change"]) == Decimal("-.075")
    assert json.loads(json.dumps(report, allow_nan=False))["replay"][-1]["Portfolio exposure"] == 150


def test_csv_order_and_close_format_do_not_change_calculations():
    original = demo_closes().decode().splitlines()
    reordered = "\n".join([original[0], *(f"{line}00" for line in reversed(original[1:]))])
    holdings = HOLDINGS_SAMPLE.decode().splitlines()
    reversed_holdings = "\n".join([holdings[0], *reversed(holdings[1:])]).encode()
    first, _ = review_portfolio(prepare_review(HOLDINGS_SAMPLE, demo_closes(), "2000", "USD"))
    second, _ = review_portfolio(prepare_review(reversed_holdings, reordered.encode(), "2000", "USD"))
    for field in ("price_dataset_id", "comparison", "risk"):
        assert first[field] == second[field]


@pytest.mark.parametrize("holding_rows,cash,expected", [
    ("XNAS,ALFA,share,USD,80\nXNAS,ALFA,share,USD,80\n", "0", "Duplicate holding"),
    ("XNAS,ALFA,share,USD,0\n", "0", "positive quantity"),
    ("XNAS,ALFA,share,AUD,80\n", "0", "must use USD"),
    ("XNAS,ALFA,share,USD,80\n", "-0.01", "non-negative cash"),
])
def test_rejects_holdings_that_cannot_be_reconciled(holding_rows, cash, expected):
    with pytest.raises(ImportIssue, match=expected):
        prepare_review((HOLDINGS_HEADER + "\n" + holding_rows).encode(), demo_closes(), cash, "USD")


def test_price_panel_fails_on_single_instrument_gap():
    prices = demo_closes().decode().splitlines()
    del prices[37]
    with pytest.raises(ImportIssue, match="Session dates differ"):
        prepare_review(HOLDINGS_SAMPLE, "\n".join(prices).encode(), "0", "USD")


def test_price_panel_fails_on_missing_instrument_and_on_nonfinite_close():
    prices = demo_closes().decode().splitlines()
    only_alfa = [line for line in prices if ",BETA," not in line]
    with pytest.raises(ImportIssue, match="Session dates differ"):
        prepare_review(HOLDINGS_SAMPLE, "\n".join(only_alfa).encode(), "0", "USD")
    prices[1] = prices[1].rsplit(",", 1)[0] + ",NaN"
    with pytest.raises(ImportIssue, match="Prices line 2:"):
        prepare_review(HOLDINGS_SAMPLE, "\n".join(prices).encode(), "0", "USD")


def test_aud_valuation_retains_currency_without_fx():
    holdings = HOLDINGS_SAMPLE.replace(b"XNAS", b"XASX").replace(b"ARCX", b"XASX").replace(b"USD", b"AUD")
    history = demo_closes().replace(b"XNAS", b"XASX").replace(b"ARCX", b"XASX").replace(b"USD", b"AUD")
    report, _ = review_portfolio(prepare_review(holdings, history, "2000", "AUD"))
    assert report["valuation"]["base_currency"] == "AUD"
    assert all(quote["currency"] == "AUD" for quote in report["valuation"]["quotes"])


def test_streamlit_demo_reviews_before_confirming_and_can_reset():
    app_path = Path(__file__).resolve().parents[1] / "src/ui/workbench.py"
    app = AppTest.from_file(app_path, default_timeout=30).run()

    def click(label):
        next(button for button in app.button if button.label == label).click().run()
        assert not app.exception

    click("Preview sample")
    assert not app.tabs
    click("Confirm and run review")
    assert len(app.tabs) == 4
    assert any(item.label == "Download review" for item in app.get("download_button"))
    click("Start over")
    assert not app.tabs
    assert not app.get("download_button")
