"""Product pages backed by the portfolio, research, storage and broker services."""
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os

import pandas as pd
import plotly.express as px
import streamlit as st

from src.ui.workbench_account import workspace
from src.workbench.broker import BROKER_OFFLINE_CASH, BROKER_OFFLINE_POSITIONS, PersonalBroker, reconcile
from src.workbench.demo import demo_fx, demo_research
from src.workbench.experiments import ExperimentConfig, experiment_report, run_experiment
from src.workbench.fx import mixed_review
from src.workbench.research_data import MAX_BARS_BYTES, MAX_NEWS_BYTES, parse_research_data
from src.workbench.sentiment import FinBertScorer


def _download(label, value, filename):
    st.download_button(label, json.dumps(value, indent=2, allow_nan=False), filename, "application/json")


def _files(group, specs):
    return [st.file_uploader(label, type="csv", key=f"{group}_{i}") for i, label in enumerate(specs)]


def research_page():
    st.title("Strategy research")
    st.caption("Compare net results on held-out sessions and measure what changes when news features are added.")
    sample = st.toggle("Use synthetic research dataset", value=True, key="research_demo")
    sample_bars, sample_news = demo_research()
    with st.expander("Input templates"):
        st.download_button("Example session bars", sample_bars, "research-bars.csv", "text/csv")
        st.download_button("Example news events", sample_news, "research-events.csv", "text/csv")
        st.write("Bars use timezone-aware open and close timestamps. Events need the publication time, first availability time and original source.")
    if sample:
        bars, news = sample_bars, sample_news
    else:
        bar_file, news_file = _files("research", ["Open and close bars", "News events (optional)"])
        if (bar_file and bar_file.size > MAX_BARS_BYTES) or (news_file and news_file.size > MAX_NEWS_BYTES):
            st.error("Research file size limits are 6 MiB for bars and 4 MiB for news.")
            return
        bars = bar_file.getvalue() if bar_file else None
        news = news_file.getvalue() if news_file else None
    left, middle, right = st.columns(3)
    fee = left.number_input("Fee (bps)", min_value=0, max_value=100, value=10)
    slip = middle.number_input("Slippage (bps)", min_value=0, max_value=100, value=5)
    frequency = right.number_input("Rebalance every N sessions", min_value=1, max_value=60, value=5)
    cash = st.slider("Minimum cash allocation (%)", 0, 90, 10)
    ppo = st.checkbox("Include experimental PPO (two seeds)", value=False)
    revision = ""
    if news and not sample and os.getenv("WORKBENCH_FINBERT_REVISION"):
        if st.checkbox("Score uploaded headlines using local FinBERT"):
            revision = os.environ["WORKBENCH_FINBERT_REVISION"]
    settings = ExperimentConfig(fee, slip, cash/100, frequency, ppo=ppo)
    mode = st.radio("Execution", ["Run now", "Queue for worker"], horizontal=True) if os.getenv("WORKBENCH_DB") and not revision else "Run now"
    if st.button("Run research comparison", type="primary", disabled=bars is None):
        st.session_state.pop("research_report", None)
        st.session_state.pop("research_events", None)
        try:
            with st.spinner("Preparing decision windows and calculating net returns"):
                if mode == "Queue for worker":
                    store, owner, _ = workspace()
                    key = store.enqueue(owner, "research", {
                        "bars": base64.b64encode(bars).decode(),
                        "news": base64.b64encode(news).decode() if news else None,
                        "config": asdict(settings), "synthetic": sample,
                    })
                    st.success(f"Queued experiment {key[:12]}. Open Saved reviews & alerts to see its result.")
                else:
                    scorer = FinBertScorer(revision) if revision else None
                    data = parse_research_data(bars, news, scorer)
                    result = experiment_report(run_experiment(data, settings), settings)
                    result["dataset_type"] = "synthetic demo" if sample else "user-supplied"
                    st.session_state["research_report"] = result
                    st.session_state["research_events"] = data.news
        except (ValueError, ArithmeticError) as exc:
            st.error(str(exc))
    result = st.session_state.get("research_report")
    if not result:
        return
    _show_research(result)
    news_data = st.session_state["research_events"]
    if not news_data.empty:
        with st.expander("News evidence"):
            st.dataframe(news_data[["instrument", "headline", "source", "published_at", "available_at", "score", "url"]],
                         hide_index=True, width="stretch", column_config={"url": st.column_config.LinkColumn("Original source")})


def _show_research(result, filename="portfolio-research.json"):
    st.caption(f"{result['dataset_type'].capitalize()} · Scores from {result['score_source']} · Dataset {result['dataset_id'][:12]}")
    metrics = pd.DataFrame({name: run["metrics"] for name, run in result["runs"].items()}).T
    curves = pd.DataFrame({
        name: pd.DataFrame(run["daily"]).set_index("session")["equity"] for name, run in result["runs"].items()
    })
    curves.index = pd.to_datetime(curves.index)
    curves.index.name = "Session"
    st.plotly_chart(px.line(curves, labels={"value": "Simulated equity", "variable": "Strategy"}), width="stretch")
    columns = {
        "period_return": "Net period return", "cagr": "Annualised growth", "volatility": "Volatility",
        "max_drawdown": "Max drawdown", "sharpe": "Sharpe", "sortino": "Sortino",
        "turnover": "Traded / equity", "fees": "Fees", "slippage": "Slippage",
    }
    st.dataframe(metrics.rename(columns=columns), width="stretch", column_config={
        columns[key]: st.column_config.NumberColumn(format="percent")
        for key in ("period_return", "cagr", "volatility", "max_drawdown", "turnover")
    })
    if result["ablation"] is not None:
        delta = result["ablation"]["period_return"]
        st.metric("Net return difference from adding sentiment", f"{100 * delta:+.2f} pp")
        st.caption("Both ridge strategies use the same trade dates, pricing, costs and ranking rules.")
        with st.expander("Ablation by 20-session window"):
            st.dataframe(pd.DataFrame(result["ablation"]["net_return_delta_by_window"]), hide_index=True)
        with st.expander("Cost sensitivity"):
            st.dataframe(pd.DataFrame(result["cost_sensitivity"]), hide_index=True, width="stretch")
    else:
        st.info("No eligible news coverage for a sentiment comparison.")
    with st.expander("Execution ledger"):
        strategy = st.selectbox("Strategy", list(result["runs"]), index=1, key=f"ledger_{filename}")
        ledger = pd.DataFrame(result["runs"][strategy]["ledger"])
        if ledger.empty:
            st.caption("This benchmark placed no trades.")
        else:
            st.dataframe(ledger, hide_index=True, width="stretch")
    st.caption("Signals use the close and execute at a later open. Tests are retrospective and can be sensitive to costs and dataset selection.")
    _download("Download experiment", result, filename)


def currency_page():
    st.title("AUD and USD analysis")
    st.caption("Include historical currency moves and foreign-currency cash when measuring exposure in your base currency.")
    sample = st.toggle("Use synthetic FX example", value=True)
    sample_files = demo_fx()
    with st.expander("CSV templates"):
        for label, name, data in zip(["Holdings", "Closing prices", "AUD per USD history"],
                                      ["fx-holdings.csv", "fx-prices.csv", "fx-rates.csv"], sample_files, strict=True):
            st.download_button(f"Example {label}", data, name, "text/csv")
    files = sample_files
    if not sample:
        uploads = _files("fx", ["Holdings CSV", "Historical closes CSV", "Historical FX CSV"])
        files = tuple(f.getvalue() if f else None for f in uploads)
    left, middle, right = st.columns(3)
    base = left.radio("Report currency", ["AUD", "USD"], horizontal=True)
    aud = middle.text_input("AUD cash", "750" if sample else "0")
    usd = right.text_input("USD cash", "1500" if sample else "0")
    if st.button("Analyse currency exposure", type="primary", disabled=any(f is None for f in files)):
        st.session_state.pop("fx_report", None)
        try:
            result = mixed_review(*files, aud, usd, base)
            result["source"] = "synthetic demo" if sample else "user-supplied observations"
            st.session_state["fx_report"] = result
        except (ValueError, ArithmeticError) as exc:
            st.error(str(exc))
    result = st.session_state.get("fx_report")
    if not result:
        return
    denom = result["base"]
    st.caption(f"{result['source'].capitalize()} · Closing session {result['as_of']} · AUD per USD {result['rate']}")
    a, b, c = st.columns(3)
    a.metric("Portfolio value", f"{denom} {float(result['total']):,.2f}")
    b.metric("95% historical VaR", f"{denom} {result['risk']['historical_var']['var_dollar']:,.2f}")
    c.metric("95% expected shortfall", f"{denom} {result['risk']['cvar_expected_shortfall']['cvar_dollar']:,.2f}")
    positions = pd.DataFrame({"Holding": result["values"].keys(),
                              f"Value ({denom})": [float(v) for v in result["values"].values()],
                              "Weight": result["weights"].values()})
    st.dataframe(positions, hide_index=True, width="stretch", column_config={"Weight": st.column_config.NumberColumn(format="percent")})
    st.plotly_chart(px.line(result["path"].rename("FX-adjusted exposure"), title="Base-currency historical replay"), width="stretch")
    st.caption("Inputs need a matching observation date and comparable market/FX cutoffs. Holidays and cross-market close-time differences must be reconciled in the supplied files.")
    serializable = {k:v for k,v in result.items() if k != "path"}
    serializable["path"] = [{"date": str(d), "index": v} for d, v in result["path"].items()]
    _download("Download FX review", serializable, "portfolio-fx.json")


def saved_page():
    st.title("Saved reviews & alerts")
    try:
        store, owner, persistent = workspace()
    except ValueError as exc:
        st.info(str(exc))
        return
    st.caption("Private saved workspace" if persistent else "Session workspace. Use downloads to keep a copy after this session ends.")
    review_tab, alerts_tab, jobs_tab = st.tabs(["Saved reviews", "Threshold alerts", "Job results"])
    with review_tab:
        reviews = store.reviews(owner)
        if reviews:
            label = {row["id"]: f"{row['name']} · saved {row['created_at'][:19]} UTC" for row in reviews}
            key = st.selectbox("Saved review", list(label), format_func=label.get)
            report = store.read_review(owner, key)
            if report:
                _download("Download saved review", report, "saved-portfolio-review.json")
                st.write(f"Valued on {report['session_end']} · {report['valuation']['base_currency']} {float(report['valuation']['total_value']):,.2f}")
                compare = st.selectbox("Compare with", [None, *[i for i in label if i != key]],
                                       format_func=lambda x: label[x] if x else "Select another review")
                if compare:
                    other = store.read_review(owner, compare)
                    if report["valuation"]["base_currency"] == other["valuation"]["base_currency"]:
                        current = {p["instrument_id"]: float(p["weight"]) for p in report["valuation"]["positions"]}
                        past = {p["instrument_id"]: float(p["weight"]) for p in other["valuation"]["positions"]}
                        rows = [{"Holding": i, "Selected weight": current.get(i, 0), "Comparison weight": past.get(i, 0),
                                 "Difference (pp)": 100*(current.get(i, 0)-past.get(i, 0))}
                                for i in sorted(set(current) | set(past))]
                        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config={
                            label: st.column_config.NumberColumn(format="percent")
                            for label in ("Selected weight", "Comparison weight")})
                        st.caption("Differences show changes in reported exposure. Trades, deposits and price moves can all change allocations.")
                    else:
                        st.info("Compare reviews in the same base currency.")
                if persistent and os.getenv("WORKBENCH_YAHOO_PERSONAL_USE") == "1" and report["source"] == "Yahoo Finance":
                    import csv
                    from io import StringIO
                    output = StringIO()
                    writer = csv.writer(output)
                    writer.writerow(["exchange", "ticker", "asset_type", "currency", "quantity"])
                    for position in report["holdings"]["positions"]:
                        inst = position["instrument"]
                        writer.writerow([inst["exchange"], inst["ticker"], inst["asset_type"], inst["currency"], position["quantity"]])
                    payload = {"holdings": base64.b64encode(output.getvalue().encode()).decode(),
                               "cash": report["valuation"]["cash"], "currency": report["valuation"]["base_currency"]}
                    if st.button("Queue price refresh"):
                        try:
                            store.enqueue(owner, "refresh", {**payload, "request_day": datetime.now(timezone.utc).date().isoformat()})
                            st.success("Refresh queued. The saved review stays available until a current result is accepted.")
                        except ValueError as exc:
                            st.error(str(exc))
                    name = next(item["name"] for item in reviews if item["id"] == key)
                    if name in store.watches(owner):
                        if st.button("Stop daily refresh"):
                            store.unwatch(owner, name)
                            st.rerun()
                    elif st.button("Start daily refresh"):
                        store.watch(owner, name, payload)
                        st.rerun()
                    st.caption("Daily refresh uses this saved holdings mix. The worker saves newer complete price sessions and evaluates your alert rules.")
                if st.button("Delete selected review"):
                    store.delete_review(owner, key)
                    st.rerun()
        else:
            st.info("Save a report from Portfolio review to compare it here.")
    with alerts_tab:
        with st.form("new_rule"):
            name = st.text_input("Portfolio name", "My portfolio", max_chars=80)
            kind = st.selectbox("Threshold type", ["Largest holding weight", "Historical VaR"])
            bound = st.number_input("Threshold (%)", min_value=.1, max_value=100., value=25.)
            if st.form_submit_button("Add alert"):
                try:
                    store.add_rule(owner, name, "largest" if kind.startswith("Largest") else "var", bound/100)
                    st.success("Rule saved.")
                except ValueError as exc:
                    st.error(str(exc))
        st.caption("An alert is evaluated when a new review with the same portfolio name is saved. Synthetic demo reports do not trigger alerts.")
        rules = store.rules(owner)
        if rules:
            rule_by_id = {row["id"]: f"{row['name']} · {row['kind']} ≥ {row['threshold']:.2%}" for row in rules}
            rule = st.selectbox("Active rules", list(rule_by_id), format_func=rule_by_id.get)
            if st.button("Remove selected rule"):
                store.delete_rule(owner, rule)
                st.rerun()
        for alert in store.alerts(owner):
            left, right = st.columns([4, 1])
            left.write(f"{alert['as_of']} · {alert['message']}")
            if not alert["acknowledged"] and right.button("Mark read", key=f"ack_{alert['id']}"):
                store.acknowledge(owner, alert["id"])
                st.rerun()
    with jobs_tab:
        if not persistent:
            st.info("Durable jobs require a configured private workspace and worker.")
        else:
            st.button("Refresh job list")
            jobs = store.jobs(owner)
            if jobs:
                job = st.selectbox("Job", range(len(jobs)), format_func=lambda i: f"{jobs[i]['kind']} · {jobs[i]['status']} · {jobs[i]['id'][:8]}")
                row = jobs[job]
                result = store.job_result(owner, row["id"])
                if result and "error" in result:
                    st.warning(result["error"])
                elif result and row["kind"] == "research":
                    _show_research(result, "queued-experiment.json")
                elif result:
                    st.write(f"Refreshed through {result['session_end']}")
                    name = st.text_input("Save refreshed review under", "My portfolio", max_chars=80)
                    if st.button("Accept refreshed review"):
                        try:
                            store.save_review(owner, name, result)
                            st.success("Refreshed review saved and alert rules evaluated.")
                        except ValueError as exc:
                            st.error(str(exc))
            else:
                st.info("No jobs submitted.")
    if persistent:
        with st.expander("Manage workspace data"):
            confirm = st.checkbox("I want to delete my saved reviews, alert rules, and jobs.")
            if st.button("Delete workspace data", disabled=not confirm):
                store.purge(owner)
                st.rerun()


def broker_page():
    st.title("Broker import")
    st.caption("Review broker-reported holdings and cash before using them in the portfolio review.")
    live = False
    broker = None
    if os.getenv("WORKBENCH_BROKER_OWNER"):
        try:
            _, owner, persistent = workspace()
            if persistent and owner == os.getenv("WORKBENCH_BROKER_OWNER"):
                broker = PersonalBroker.for_owner(owner)
                live = True
        except ValueError as exc:
            st.warning(str(exc))
    if not live:
        st.caption("Offline broker example. Live access uses an owner-bound SnapTrade Personal connection.")
        if st.button("Load sample broker holdings"):
            st.session_state["broker_snapshot"] = {**reconcile(BROKER_OFFLINE_POSITIONS, BROKER_OFFLINE_CASH),
                                                      "freshness": "Synthetic broker fixture"}
    else:
        if st.button("Generate read-only connection link"):
            try:
                st.session_state["broker_portal"] = broker.portal()
            except Exception:
                st.error("Connection link is unavailable. Check your SnapTrade configuration.")
        if st.session_state.get("broker_portal"):
            st.link_button("Open secure broker portal", st.session_state["broker_portal"])
        if st.button("List connected accounts"):
            try:
                st.session_state["broker_accounts"] = broker.accounts()
            except Exception:
                st.error("Could not list broker accounts.")
        accounts = st.session_state.get("broker_accounts", [])
        if accounts:
            index = st.selectbox("Account", range(len(accounts)),
                                 format_func=lambda i: accounts[i].get("name", f"Account {i+1}"))
            account = accounts[index]
            if st.button("Import holdings and cash"):
                try:
                    st.session_state["broker_snapshot"] = broker.sync(account)
                except ValueError as exc:
                    st.warning(str(exc))
                except Exception:
                    st.error("Broker sync failed. The last successful import is retained.")
            if st.button("Generate reconnect link"):
                try:
                    st.link_button("Reconnect in SnapTrade", broker.portal(account["brokerage_authorization"]))
                except Exception:
                    st.error("The reconnect link is unavailable.")
            with st.expander("Disconnect linked brokerage"):
                st.caption("A brokerage connection can include more than one account.")
                confirm = st.checkbox("Disconnect all accounts under this connection")
                if st.button("Disconnect from SnapTrade", disabled=not confirm):
                    try:
                        broker.disconnect(account["brokerage_authorization"])
                    except Exception:
                        st.error("Disconnect failed. Check the connection in SnapTrade.")
                    else:
                        for key in ("broker_snapshot", "broker_accounts", "broker_portal"):
                            st.session_state.pop(key, None)
                        st.rerun()
    snapshot = st.session_state.get("broker_snapshot")
    if snapshot:
        from io import StringIO
        st.caption(snapshot["freshness"])
        if snapshot.get("retrieved_at"):
            st.write(f"Retrieved {snapshot['retrieved_at']}")
        st.dataframe(pd.read_csv(StringIO(snapshot["holdings"]), dtype=str), hide_index=True, width="stretch")
        st.write("Cash balances")
        st.table(pd.DataFrame([{"Currency": code, "Cash": amount} for code, amount in snapshot["cash"].items()]))
        st.download_button("Download broker holdings CSV", snapshot["holdings"], "broker-holdings.csv", "text/csv")
        _download("Download broker cash balances", snapshot["cash"], "broker-cash.json")
        if st.button("Use broker holdings in a review"):
            st.session_state["use_broker_import"] = True
            st.switch_page("src/ui/workbench.py")
