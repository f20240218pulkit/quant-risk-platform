"""Standalone Streamlit entry point for local portfolio review."""
from dataclasses import replace
from decimal import Decimal
import json
import os

import pandas as pd
import plotly.express as px
import streamlit as st

from src.workbench.demo import HOLDINGS_SAMPLE, demo_closes
from src.workbench.inputs import MAX_HOLDINGS_BYTES, MAX_PRICES_BYTES
from src.workbench.review import confirm_review, prepare_review, review_portfolio, shock_position
from src.workbench.market import extended_risk, historical_crises, prepare_market_review
from src.ui.workbench_account import workspace

st.set_page_config(page_title="Portfolio Workbench", page_icon="◈", layout="wide")
st.title("Portfolio Workbench")
st.caption("Review your holdings, test a price shock and compare exposures over a common historical window.")


def clear_review():
    for key in ("draft", "review", "confirmed", "shock_asset", "shock_pct", "extra_risk", "crisis_results"):
        st.session_state.pop(key, None)


def start_over():
    clear_review()
    st.session_state["upload_generation"] = st.session_state.get("upload_generation", 0) + 1
    for key in ("cash", "currency", "mode"):
        st.session_state.pop(key, None)


def review_table(prepared):
    valuation = prepared.valuation
    table = [{
        "Holding": item.instrument_id,
        "Quantity": str(item.quantity),
        "Close": str(quote.price),
        f"Value ({valuation.base_currency})": f"{item.market_value:,.2f}",
        "Weight": f"{item.weight:.2%}",
    } for item, quote in zip(valuation.positions, valuation.quotes, strict=True)]
    table.append({
        "Holding": "Cash", "Quantity": "—", "Close": "—",
        f"Value ({valuation.base_currency})": f"{valuation.cash:,.2f}",
        "Weight": f"{valuation.cash_weight:.2%}",
    })
    return pd.DataFrame(table)


with st.sidebar:
    st.header("Portfolio inputs")
    sources = ["Sample portfolio", "Upload CSVs"]
    if os.getenv("WORKBENCH_YAHOO_PERSONAL_USE") == "1":
        sources.append("Fetch market closes")
    if st.session_state.get("broker_snapshot"):
        sources.append("Broker import")
    if st.session_state.pop("use_broker_import", False):
        clear_review()
        st.session_state["mode"] = "Broker import"
    mode = st.radio("Source", sources, key="mode", on_change=clear_review)
    st.button("Start over", on_click=start_over)
    if mode == "Upload CSVs":
        st.caption("Use holdings and end-of-day closes in a single currency. Provide the same 253–2,500 dates for every holding.")
        st.download_button("Holdings template", HOLDINGS_SAMPLE, "holdings-template.csv", "text/csv")
        st.download_button("Example close history", demo_closes(), "closes-example.csv", "text/csv")
        generation = st.session_state.get("upload_generation", 0)
        holdings_file = st.file_uploader("Holdings CSV", type="csv", key=f"holdings_{generation}", on_change=clear_review)
        close_file = st.file_uploader("Historical closes CSV", type="csv", key=f"closes_{generation}", on_change=clear_review)
        currency = st.selectbox("Currency", ["USD", "AUD"], key="currency", on_change=clear_review)
        cash = st.text_input("Cash balance", value="0", key="cash", on_change=clear_review)
        preview = st.button("Preview holdings", type="primary", disabled=holdings_file is None or close_file is None)
        if preview:
            clear_review()
            if holdings_file.size > MAX_HOLDINGS_BYTES or close_file.size > MAX_PRICES_BYTES:
                st.error("File limits are 64 KiB for holdings and 6 MiB for closes.")
            else:
                try:
                    st.session_state["draft"] = prepare_review(
                        holdings_file.getvalue(), close_file.getvalue(), cash, currency,
                    )
                except ValueError as exc:
                    st.error(str(exc))
    elif mode == "Broker import":
        snapshot = st.session_state["broker_snapshot"]
        synthetic = snapshot["freshness"] == "Synthetic broker fixture"
        for code, amount in snapshot["cash"].items():
            st.caption(f"Broker cash · {code} {amount}")
        market_available = os.getenv("WORKBENCH_YAHOO_PERSONAL_USE") == "1"
        auto = market_available and not synthetic and st.checkbox("Fetch completed market closes", on_change=clear_review)
        prices = None
        if not synthetic and not auto:
            prices = st.file_uploader("Historical closes CSV", type="csv",
                                      key="broker_history", on_change=clear_review)
        if st.button("Preview imported holdings", type="primary", disabled=not (synthetic or auto or prices)):
            clear_review()
            try:
                raw = snapshot["holdings"].encode()
                currencies = {line.split(",")[3] for line in snapshot["holdings"].splitlines()[1:]}
                if len(currencies) != 1:
                    raise ValueError("Use the AUD and USD analysis screen for a multi-currency broker portfolio.")
                currency = currencies.pop()
                if any(code != currency and Decimal(amount) != 0 for code, amount in snapshot["cash"].items()):
                    raise ValueError("Use AUD and USD analysis to preserve foreign-currency cash.")
                cash = snapshot["cash"].get(currency, "0")
                if auto:
                    draft = prepare_market_review(raw, cash, currency)
                else:
                    draft = prepare_review(raw, demo_closes() if synthetic else prices.getvalue(), cash, currency, demo=synthetic)
                holdings = draft.holdings.model_copy(update={"source": "broker"})
                st.session_state["draft"] = replace(draft, holdings=holdings)
            except ValueError as exc:
                st.error(str(exc))
    elif mode == "Fetch market closes":
        st.caption("Yahoo Finance personal-use mode. Upload exchange-qualified holdings. The provider checks listing metadata.")
        market_file = st.file_uploader("Holdings CSV", type="csv", key="market_holdings", on_change=clear_review)
        market_currency = st.selectbox("Currency", ["USD", "AUD"], key="market_currency", on_change=clear_review)
        market_cash = st.text_input("Cash balance", value="0", key="market_cash", on_change=clear_review)
        if st.button("Fetch and preview", type="primary", disabled=market_file is None):
            clear_review()
            with st.spinner("Validating listings and completed sessions"):
                try:
                    st.session_state["draft"] = prepare_market_review(
                        market_file.getvalue(), market_cash, market_currency,
                    )
                except ValueError as exc:
                    st.error(str(exc))
    else:
        st.caption("Synthetic prices for two fictional holdings. Useful for learning the workflow.")
        if st.button("Preview sample", type="primary"):
            clear_review()
            st.session_state["draft"] = prepare_review(HOLDINGS_SAMPLE, demo_closes(), "2000", "USD", demo=True)

draft = st.session_state.get("draft")
if draft is None:
    st.info("Preview the sample portfolio or upload holdings and a matching set of closing prices.")
    st.stop()

valuation = draft.valuation
currency = valuation.base_currency
st.subheader("Holdings and cash")
st.caption(
    f"{valuation.quotes[0].source.capitalize()} · Value at the latest supplied close "
    f"({draft.closes.index[-1]}) · {currency}"
)
a, b, c = st.columns(3)
a.metric("Total value", f"{currency} {valuation.total_value:,.2f}")
b.metric("Cash weight", f"{valuation.cash_weight:.1%}")
largest = max(valuation.positions, key=lambda position: position.weight)
c.metric("Largest security weight", f"{largest.weight:.1%}", largest.instrument_id, delta_color="off")
st.dataframe(review_table(draft), hide_index=True, width="stretch")

if st.button("Confirm and run review", type="primary"):
    for key in ("review", "confirmed", "extra_risk", "crisis_results"):
        st.session_state.pop(key, None)
    try:
        confirmed = confirm_review(draft)
        report, paths = review_portfolio(confirmed)
        st.session_state["review"] = report, paths
        st.session_state["confirmed"] = confirmed
    except ValueError as exc:
        st.error(str(exc))

review = st.session_state.get("review")
if review is None:
    st.caption("Check the quantities, cash and closing prices against your records before confirming.")
    st.stop()

report, paths = review
risk_tab, comparison_tab, scenario_tab, models_tab = st.tabs(
    ["Downside risk", "Historical comparison", "Price shock", "Simulation & optimisation"]
)
with risk_tab:
    a, b = st.columns(2)
    a.metric("95% historical VaR", f"{currency} {report['risk']['historical_var']['var_dollar']:,.2f}")
    b.metric("95% expected shortfall", f"{currency} {report['risk']['cvar_expected_shortfall']['cvar_dollar']:,.2f}")
    st.caption(
        f"One-session estimates based on {report['return_observations']} returns. "
        "VaR estimates a loss threshold. Expected shortfall averages the observations in the estimated loss tail."
    )
with comparison_tab:
    chart = px.line(paths, labels={"index": "Session", "value": "Indexed value", "variable": "Exposure"})
    st.plotly_chart(chart, width="stretch")
    comparisons = [{
        "Exposure": name, "Period return": f"{metrics['terminal_return']:.2%}",
        "Maximum drawdown": f"{metrics['max_drawdown']:.2%}",
    } for name, metrics in report["comparison"].items()]
    st.dataframe(pd.DataFrame(comparisons), hide_index=True, width="stretch")
    st.caption(
        "Hypothetical replay of the valuation-date exposure mix over the supplied history. Both paths start at 100 "
        "with the same cash weight and allow asset weights to drift. They exclude trading costs and corporate actions."
    )
with scenario_tab:
    asset = st.selectbox("Holding to shock", [item.instrument_id for item in valuation.positions], key="shock_asset")
    change = st.slider("Price change (%)", -100, 100, -15, key="shock_pct")
    scenario = shock_position(valuation, asset, Decimal(change) / 100)
    a, b = st.columns(2)
    a.metric("Portfolio change", f"{Decimal(scenario['portfolio_change']):+.2%}")
    b.metric("Shocked total", f"{currency} {Decimal(scenario['shocked_equity']):,.2f}",
             f"{Decimal(scenario['pnl']):+,.2f} {currency}")
    st.caption("Instantaneous change to the selected holding. All other holdings and cash stay fixed.")

with models_tab:
    st.caption("Historical correlations and model scenarios use the confirmed observations and cash weight.")
    horizon = st.slider("Simulation horizon (sessions)", 1, 40, 10, key="mc_days")
    if st.button("Run simulation and optimisation"):
        st.session_state.pop("extra_risk", None)
        try:
            st.session_state["extra_risk"] = extended_risk(st.session_state["confirmed"], days=horizon)
        except ValueError as exc:
            st.error(str(exc))
    advanced = st.session_state.get("extra_risk")
    if advanced:
        summary = advanced["simulation"]
        chart = pd.DataFrame(summary["percentiles"])
        chart.index.name = "Session"
        st.plotly_chart(px.line(chart, labels={"value": f"Model equity ({currency})"}), width="stretch")
        st.caption(f"{len(chart)-1} sessions, {summary['n_simulations']:,} paths, seed {summary['seed']}.")
        st.metric("Simulated 95% VaR", f"{currency} {summary['mc_var_dollar']:,.2f}")
        corr = advanced["correlation"]
        st.plotly_chart(px.imshow(corr, zmin=-1, zmax=1, color_continuous_scale="RdBu_r",
                                  title="Daily return correlation"), width="stretch")
        if advanced["optimisation"]:
            st.dataframe(pd.DataFrame({key: result["weights"]
                                       for key, result in advanced["optimisation"].items()}),
                         width="stretch")
            if advanced["frontier"]:
                st.plotly_chart(px.line(pd.DataFrame(advanced["frontier"]), x="volatility", y="return",
                                       markers=True, title="Hypothetical efficient frontier"), width="stretch")
            st.caption("Model mixes hold cash allocation fixed. Expected returns are estimated from past observations.")
        else:
            st.info(advanced["optimiser_status"])
    if draft.source == "Yahoo Finance" and st.button("Replay historical crises"):
        st.session_state["crisis_results"] = historical_crises(st.session_state["confirmed"])
    if st.session_state.get("crisis_results"):
        for label, result in st.session_state["crisis_results"].items():
            if "max_drawdown_pct" in result:
                st.metric(f"{label} drawdown", f"{result['max_drawdown_pct']:.2%}")
            else:
                st.warning(f"{label} · {result['reason']}")
    elif draft.source != "Yahoo Finance":
        st.caption("Named crisis windows use the optional historical market-data connection.")

export = {**report, "scenario": scenario}
advanced = st.session_state.get("extra_risk")
if advanced:
    export["extended_risk"] = {key: val for key, val in advanced.items() if key != "correlation"}
    export["extended_risk"]["correlation"] = json.loads(advanced["correlation"].to_json())
if "crisis_results" in st.session_state:
    export["crisis_replay"] = st.session_state["crisis_results"]

st.download_button(
    "Download review",
    json.dumps(export, indent=2, allow_nan=False),
    "portfolio-review.json", "application/json",
)
with st.expander("Data and assumptions"):
    st.write(f"Observed sessions: {report['session_start']} to {report['session_end']}.")
    st.code(report["price_dataset_id"], language=None)
    st.write("Keep the source price file with the report to reproduce the full review.")
    for assumption in report["assumptions"]:
        st.write(f"• {assumption}")

with st.expander("Save to workspace"):
    name = st.text_input("Portfolio name", value="My portfolio", max_chars=80)
    if st.button("Save review"):
        try:
            store, owner, persistent = workspace()
            store.save_review(owner, name, export)
            st.success("Review saved." if persistent else "Review saved for this browser session.")
        except ValueError as exc:
            st.error(str(exc))
