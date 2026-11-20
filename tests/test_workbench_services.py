import base64
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from src.workbench.broker import BROKER_OFFLINE_CASH, BROKER_OFFLINE_POSITIONS, reconcile
from src.workbench.demo import HOLDINGS_SAMPLE, demo_research, demo_fx, demo_closes
from src.workbench.experiments import ExperimentConfig
from src.workbench.fx import mixed_review
from src.workbench.inputs import ImportIssue
from src.workbench.market import extended_risk, prepare_market_review
from src.workbench.review import prepare_review, review_portfolio
from src.workbench.storage import Store, identity_key
from src.workbench.worker import process_one


def test_market_uses_raw_quote_and_adjusted_history():
    today = date(2025, 10, 2)

    def provider(position, start, end):
        dates = pd.date_range(end=today - timedelta(days=1), periods=253).date
        return pd.DataFrame({"Close": 200., "Adj Close": range(100, 353)}, index=dates)

    prepared = prepare_market_review(HOLDINGS_SAMPLE, "2000", "USD", today=today, get_history=provider)
    assert prepared.valuation.total_value == 25_000
    assert prepared.closes.iloc[-1].iat[0] == 352
    assert prepared.source == "Yahoo Finance"
    assert len(extended_risk(prepared, days=2, paths=101)["simulation"]["percentiles"]["p50"]) == 3


def test_foreign_cash_and_flat_foreign_asset_both_move_with_fx():
    holdings, bar_data, rates = demo_fx()
    flat = "\n".join(row.rsplit(",", 1)[0] + ",100" for row in bar_data.decode().splitlines()[1:])
    flat = (bar_data.decode().splitlines()[0] + "\n" + flat).encode()
    result = mixed_review(holdings, flat, rates, "750", "1500", "AUD")
    last_rate = Decimal(result["rate"])
    assert Decimal(result["total"]) == (Decimal(80) * 100 + 1500) * last_rate + 3500 + 750
    foreign_exposure = result["weights"]["XNAS:ALFA"] + result["weights"]["Cash USD"]
    assert result["replay"]["terminal_return"] == pytest.approx(foreign_exposure * (float(last_rate) / 1.4 - 1))


def test_broker_cash_equivalents_are_not_double_counted_and_empty_fails():
    balances = reconcile([*BROKER_OFFLINE_POSITIONS, {"cash_equivalent": True}], BROKER_OFFLINE_CASH)
    assert balances["cash"] == {"USD": "2000"}
    assert balances["holdings"].count("\n") == 3
    with pytest.raises(ImportIssue, match="previous"):
        reconcile([], BROKER_OFFLINE_CASH)


def test_review_ownership_alert_dedupe_and_purge(tmp_path):
    storage = Store(tmp_path / "workbench.sqlite3")
    report, _ = review_portfolio(prepare_review(HOLDINGS_SAMPLE, demo_closes(), "2000", "USD"))
    storage.add_rule("alpha", "Test portfolio", "largest", .1)
    key = storage.save_review("alpha", "Test portfolio", report)
    storage.save_review("alpha", "Test portfolio", report)
    assert len(storage.alerts("alpha")) == 1
    assert storage.read_review("beta", key) is None
    assert not storage.delete_review("beta", key)
    assert storage.alerts("beta") == []
    storage.purge("alpha")
    assert not storage.reviews("alpha")
    assert not storage.alerts("alpha")


def test_owner_key_uses_issuer_and_rejects_expired_sessions():
    assert identity_key("https://a", "user-1", 11, now=10) != identity_key("https://b", "user-1", 11, now=10)
    with pytest.raises(ValueError, match="expired"):
        identity_key("https://a", "user-1", 10, now=10)


def test_worker_reclaims_lease_and_rejects_stale_results(tmp_path):
    storage = Store(tmp_path / "workbench.sqlite3")
    payload = {"bars": "test"}
    key = storage.enqueue("alpha", "research", payload, now=1)
    assert storage.enqueue("alpha", "research", payload, now=2) == key
    old = storage.claim(now=1, lease_seconds=2)
    new = storage.claim(now=4, lease_seconds=2)
    assert new["attempts"] == 2
    assert not storage.finish(old, {"result": 2}, now=4)
    assert storage.finish(new, {"result": 3}, now=4)
    assert storage.job_result("alpha", key) == {"result": 3}
    assert storage.job_result("beta", key) is None


def test_worker_processes_actual_research_report(tmp_path):
    bars, news = demo_research()
    storage = Store(tmp_path / "workbench.sqlite3")
    key = storage.enqueue("alpha", "research", {
        "bars": base64.b64encode(bars).decode(), "news": base64.b64encode(news).decode(),
        "config": asdict(ExperimentConfig()),
    })
    assert process_one(storage)
    assert storage.jobs("alpha")[0]["status"] == "complete"
    assert "Price + sentiment ridge" in storage.job_result("alpha", key)["runs"]
