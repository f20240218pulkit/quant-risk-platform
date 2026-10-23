"""Streamlit portfolio analytics dashboard backed by the hosted FastAPI API."""
import html
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from src.ui.components.charts import (
    plot_efficient_frontier,
    plot_monte_carlo_fan_chart,
    plot_stress_test_drawdowns,
)

API_BASE_URL = os.environ.get(
    "API_BASE_URL", "https://quant-risk-platform-iu77-beta.vercel.app"
).strip().rstrip("/")
st.set_page_config(page_title="Quant | Portfolio Intelligence", page_icon="◈", layout="wide")

st.markdown("""
<style>
:root {color-scheme:dark; --ink:#edf2f7; --muted:#8c9bb0; --line:#263245; --gold:#d6b777;}
html, body, [data-testid="stAppViewContainer"], .stApp {background:#0b1018;color:var(--ink);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;}
[data-testid="stHeader"] {background:transparent;}
[data-testid="stToolbarActionButton"] {display:none!important;}
[data-testid="stSidebar"] {background:#101722;border-right:1px solid #263245;}
[data-testid="stSidebar"] > div:first-child {padding-top:2rem;}
[data-testid="stMainBlockContainer"] {max-width:1440px;padding:2.2rem 3rem 2rem;}
h1,h2,h3 {font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;letter-spacing:-.035em;color:#edf2f7;}
h1 {font-size:2.6rem!important;font-weight:550!important;line-height:1.12!important;padding:0!important;}
h3 {font-size:1.14rem!important;font-weight:550!important;}
p, label, [data-testid="stCaptionContainer"] {color:#8c9bb0;}
[data-testid="stSidebar"] label p {font-size:.79rem;color:#a7b4c6;}
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input {color:#edf2f7;background:#151f2d;font-size:.85rem;}
[data-baseweb="input"], [data-baseweb="base-input"] {background:#151f2d!important;border-color:#2a374b!important;border-radius:8px!important;}
[data-testid="stNumberInput"] button {background:#151f2d;color:#a7b4c6;}
[data-testid="stSlider"] [role="slider"] {background:#d6b777;}
[data-testid="stBaseButton-primary"] {background:#d6b777!important;border:1px solid #d6b777!important;border-radius:8px!important;min-height:2.9rem;color:#111722!important;font-weight:650;box-shadow:0 4px 18px #d6b77715;}
[data-testid="stBaseButton-primary"] p {color:#111722!important;font-size:.86rem;}
[data-testid="stBaseButton-primary"]:hover {background:#e7c98b!important;border-color:#e7c98b!important;}
[data-testid="stTabs"] [role="tablist"] {gap:2rem;border-bottom:1px solid #263245;}
[data-testid="stTabs"] [role="tab"] {background:transparent;color:#8c9bb0;padding:.75rem 0;font-size:.86rem;}
[data-testid="stTabs"] [role="tab"] p {font-size:.86rem;}
[data-testid="stTabs"] [aria-selected="true"] p {color:#e6c687!important;}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {background:#d6b777;}
[data-testid="stTabs"] [data-baseweb="tab-border"] {background:transparent;}
[data-testid="stMetric"] {background:#111a26;border:1px solid #263245;border-radius:12px;padding:1.25rem 1.3rem;}
[data-testid="stMetricLabel"] p {font-size:.78rem!important;color:#8c9bb0;}
[data-testid="stMetricValue"] {font-family:Inter,sans-serif;font-size:1.85rem;font-weight:500;letter-spacing:-.04em;color:#edf2f7;}
[data-testid="stMetricDelta"] {font-size:.76rem;}
[data-testid="stPlotlyChart"] {border:1px solid #263245;border-radius:12px;overflow:hidden;background:#111a26;}
[data-testid="stExpander"] {background:#111a26;border-color:#263245;border-radius:9px;}
[data-testid="stDataFrame"] {border:1px solid #263245;border-radius:9px;}
[data-testid="stAlert"] {border:1px solid #263245;border-radius:9px;}
[data-testid="stMarkdownContainer"] a {color:#d6b777;}
.q-brand {font-size:1.22rem;letter-spacing:.2em;font-weight:650;color:#edf2f7;margin-bottom:3px;}
.q-brand span {color:#d6b777;}
.q-mono {font:10px ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.16em;color:#8190a6;text-transform:uppercase;}
.q-side-divider {border-top:1px solid #263245;margin:1.4rem 0 1.2rem;}
.q-side-title {font-size:.93rem;font-weight:600;color:#e4eaf2;margin:0 0 4px;}
.q-side-copy {font-size:.77rem;line-height:1.65;color:#8190a6;margin-bottom:1rem;}
.q-topline {display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #263245;padding-bottom:1.2rem;margin-bottom:2.2rem;gap:1rem;}
.q-breadcrumb {font:11px ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.12em;color:#8494aa;}
.q-breadcrumb b {color:#edf2f7;font-weight:500;}
.q-status {font-size:11px;color:#75cbb3;white-space:nowrap;border:1px solid #2b4a44;border-radius:20px;padding:5px 10px;background:#132622;}
.q-status.offline {color:#eea6a0;border-color:#623c3c;background:#2d1e23;}
.q-eyebrow {font:10px ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.18em;color:#d6b777;margin-bottom:12px;}
.q-subtitle {max-width:650px;color:#8c9bb0;font-size:.94rem;line-height:1.8;margin:1rem 0 1.6rem;}
.q-strip {display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr;background:#111a26;border:1px solid #263245;border-radius:12px;margin:.25rem 0 1.6rem;}
.q-strip-cell {padding:1.1rem 1.4rem;border-right:1px solid #263245;}
.q-strip-cell:last-child {border-right:none;}
.q-strip-value {font-size:1.2rem;color:#edf2f7;letter-spacing:-.025em;margin-top:6px;}
.q-section {display:flex;justify-content:space-between;align-items:center;margin:1.6rem 0 1rem;gap:1rem;}
.q-section-title {font-size:1.1rem;font-weight:550;letter-spacing:-.025em;color:#edf2f7;}
.q-section-note {font:10px ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.06em;color:#8190a6;}
.q-note {border-left:2px solid #d6b777;padding:.8rem 1rem;background:#141d28;border-radius:0 8px 8px 0;font-size:.83rem;line-height:1.8;color:#a4b2c4;margin:1.1rem 0;}
.q-note b {color:#e5cc9c;font-weight:550;}
.q-empty {border:1px solid #263245;border-radius:12px;padding:2.7rem;background:radial-gradient(ellipse at 95% 10%,#26304765,transparent 60%),#111a26;margin-top:1rem;}
.q-empty h2 {font-size:1.5rem;font-weight:500;margin:12px 0;color:#e6edf5;}
.q-empty p {max-width:540px;line-height:1.9;font-size:.88rem;color:#8c9bb0;}
.q-empty-icon {font-size:28px;color:#d6b777;}
.q-feature {border-top:1px solid #263245;margin-top:1.4rem;padding-top:1rem;}
.q-feature strong {display:block;font-size:.83rem;color:#dce5ef;font-weight:500;margin-bottom:7px;}
.q-feature p {font-size:.78rem;line-height:1.75;color:#8190a6;}
.q-footer {display:flex;justify-content:space-between;border-top:1px solid #263245;margin-top:2.5rem;padding-top:1rem;font:10px ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.04em;color:#697b93;gap:1rem;}
@media(max-width:900px) {[data-testid="stMainBlockContainer"] {padding:2.7rem 1.2rem 1rem;}h1 {font-size:2rem!important;}.q-strip {grid-template-columns:1fr 1fr;}.q-strip-cell {border-bottom:1px solid #263245;padding:1rem;}.q-strip-cell:nth-child(2) {border-right:0;}.q-strip-cell:nth-child(n+3) {border-bottom:0;}.q-topline {margin-bottom:1.7rem;}.q-breadcrumb {font-size:9px;}.q-empty {padding:1.5rem;}.q-section-note {font-size:9px;}.q-footer {flex-direction:column;}}
</style>
""", unsafe_allow_html=True)


def markup(text):
    st.markdown(text, unsafe_allow_html=True)


@st.cache_data(ttl=30, show_spinner=False)
def api_online(base_url):
    try:
        response = requests.get(f"{base_url}/", timeout=(10, 30))
        return response.ok and response.json().get("status") == "online"
    except (requests.RequestException, ValueError, AttributeError):
        return False


def request_analysis(endpoint, payload):
    try:
        response = requests.post(f"{API_BASE_URL}{endpoint}", json=payload, timeout=(10, 120))
        try:
            result = response.json()
        except ValueError:
            return {"error": f"Service returned HTTP {response.status_code}. Please retry shortly."}
        if not response.ok:
            detail = result.get("detail", "Please retry shortly.") if isinstance(result, dict) else result
            return {"error": f"Request failed (HTTP {response.status_code}): {detail}"}
        if not isinstance(result, dict) or result.get("status") != "success" or not isinstance(result.get("data"), dict):
            return {"error": "The service returned an unexpected response. Please retry."}
        return result
    except requests.Timeout:
        return {"error": "This calculation timed out. Try again with fewer assets."}
    except requests.RequestException:
        return {"error": "Cannot reach the analytics service. Please retry shortly."}


def section(title, note):
    markup(f'<div class="q-section"><span class="q-section-title">{html.escape(title)}</span><span class="q-section-note">{html.escape(note)}</span></div>')


with st.sidebar:
    markup('<div class="q-brand"><span>◈</span> QUANT</div><div class="q-mono">PORTFOLIO INTELLIGENCE</div><div class="q-side-divider"></div><div class="q-side-title">Portfolio workspace</div><div class="q-side-copy">Define your holdings. Understand your exposure.</div>')
    tickers_input = st.text_input("Asset universe", "AAPL, MSFT, NVDA, SPY, GLD", help="Comma-separated market tickers.")
    tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
    valid = bool(tickers) and len(tickers) == len(set(tickers))
    if not tickers:
        st.warning("Enter at least one ticker.")
    elif not valid:
        st.warning("Please enter each ticker only once.")
    portfolio_value = st.number_input("Portfolio value · USD", min_value=1.0, value=100000.0, step=5000.0)
    markup('<div class="q-side-divider"></div><div class="q-mono">MODEL PARAMETERS</div>')
    confidence = st.slider("Confidence level", .90, .99, .95, .01)
    horizon = st.slider("Simulation horizon · trading days", 1, 60, 10)
    paths = min(10000, 120000 // (horizon + 1))
    weights = []
    with st.expander("Allocation weights", expanded=True):
        if valid:
            for ticker in tickers:
                weights.append(st.number_input(f"{ticker} · %", min_value=0.0, max_value=100.0, value=round(100 / len(tickers), 2), key=f"weight_{ticker}") / 100)
        total = sum(weights)
        if valid and total <= 0:
            st.warning("At least one weight must be greater than zero.")
        elif valid:
            st.caption("Weights are normalised to 100% when you run.")
    valid = valid and total > 0
    run = st.button("Run portfolio analysis  →", type="primary", width="stretch", disabled=not valid)
    st.caption(f"{paths:,} simulation paths · Historical daily prices")

online = api_online(API_BASE_URL)
status = "API connected" if online else "API unavailable"
markup(f'<div class="q-topline"><div class="q-breadcrumb"><b>QUANT</b> &nbsp; / &nbsp; ANALYTICS WORKSPACE</div><span class="q-status {"" if online else "offline"}">● &nbsp; {status}</span></div><div class="q-eyebrow">RISK. ALLOCATION. RESILIENCE.</div>')
st.title("Portfolio intelligence.")
markup('<div class="q-subtitle">A clearer view of your portfolio. Measure downside exposure, explore optimal allocations, and test resilience across market regimes.</div>')
weights = [w / total for w in weights] if valid else []
signature = (tuple(tickers), tuple(weights), portfolio_value, confidence, horizon, paths)

if run and valid:
    payload = {"tickers": tickers, "weights": weights, "portfolio_value": portfolio_value}
    requests_to_run = {
        "risk": ("/api/v1/risk", {**payload, "confidence_level": confidence}),
        "simulation": ("/api/v1/monte-carlo", {**payload, "confidence_level": confidence, "days": horizon, "n_simulations": paths}),
        "optimisation": ("/api/v1/optimize", {"tickers": tickers, "risk_free_rate": .02}),
        "stress": ("/api/v1/stress-test", payload),
    }
    with st.status("Analysing your portfolio…", expanded=True) as progress:
        results = {}
        for key, (endpoint, body) in requests_to_run.items():
            st.write({"risk": "Calculating downside risk", "simulation": "Simulating portfolio trajectories", "optimisation": "Solving optimal allocations", "stress": "Replaying historical crises"}[key])
            results[key] = request_analysis(endpoint, body)
        failures = sum("error" in r for r in results.values())
        progress.update(label="Analysis complete" if not failures else "Analysis complete with unavailable results", state="complete" if not failures else "error", expanded=False)
    st.session_state["analysis"] = {
        "results": results, "signature": signature, "value": portfolio_value,
        "tickers": tickers[:], "weights": weights[:], "confidence": confidence,
        "horizon": horizon, "paths": paths, "time": datetime.now(timezone.utc).strftime("%d %b %Y · %H:%M UTC"),
    }

snapshot = st.session_state.get("analysis")
shown_value = snapshot["value"] if snapshot else portfolio_value
shown_assets = snapshot["tickers"] if snapshot else tickers
shown_confidence = snapshot["confidence"] if snapshot else confidence
shown_horizon = snapshot["horizon"] if snapshot else horizon
strip = [("PORTFOLIO VALUE", f"${shown_value:,.0f}"), ("ASSET UNIVERSE", f"{len(shown_assets):02d} holdings"), ("CONFIDENCE LEVEL", f"{shown_confidence:.0%}"), ("SIMULATION HORIZON", f"{shown_horizon} trading days")]
markup('<div class="q-strip">'+''.join(f'<div class="q-strip-cell"><div class="q-mono">{label}</div><div class="q-strip-value">{value}</div></div>' for label, value in strip)+'</div>')
if snapshot and snapshot["signature"] != signature:
    st.info("Portfolio inputs have changed. Run analysis to update the results shown below.")
if not online:
    st.warning("The analytics service is temporarily unavailable. You can retry the analysis shortly.")

if not snapshot:
    markup('<div class="q-empty"><div class="q-eyebrow">YOUR ANALYTICAL ADVANTAGE</div><div class="q-empty-icon">◈</div><h2>Every portfolio tells a story.</h2><p>Start with your holdings. Run an analysis to reveal the risks, trade-offs, and allocations behind your portfolio.</p><div class="q-mono">CONFIGURE IN THE SIDEBAR &nbsp; → &nbsp; RUN PORTFOLIO ANALYSIS</div></div>')
    for col, title, copy in zip(st.columns(3), ["01 / Downside intelligence", "02 / Portfolio construction", "03 / Crisis resilience"], ["Parametric and historical VaR, expected shortfall, and correlated return simulations.", "Explore the efficient frontier and compare maximum Sharpe with minimum variance allocations.", "Replay the 2008 financial crisis, COVID shock, and 2022 rate-hike sell-off."]):
        with col:
            markup(f'<div class="q-feature"><strong>{title}</strong><p>{copy}</p></div>')
else:
    st.caption(" / ".join(snapshot["tickers"]) + "   ·   Calculated " + snapshot["time"])
    tabs = st.tabs(["Risk overview", "Monte Carlo", "Portfolio optimisation", "Stress testing"])
    results = snapshot["results"]
    chart_config = {"displaylogo": False, "scrollZoom": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}
    with tabs[0]:
        section("Downside exposure", f"{snapshot['confidence']:.0%} CONFIDENCE · 1-DAY HORIZON")
        result = results["risk"]
        if "error" in result:
            st.error(result["error"])
        else:
            data = result["data"]
            for col, label, metric, pct, dollar in zip(st.columns(3), ["Parametric VaR", "Historical VaR", "Expected shortfall"], [data["parametric_var"], data["historical_var"], data["cvar_expected_shortfall"]], ["var_pct", "var_pct", "cvar_pct"], ["var_dollar", "var_dollar", "cvar_dollar"]):
                with col:
                    st.metric(label, f"${metric[dollar]:,.2f}", f"{metric[pct]:.2%} of portfolio", delta_color="off")
            tail = data["cvar_expected_shortfall"]["cvar_dollar"]
            markup(f'<div class="q-note"><b>Beyond the threshold.</b> In the historical tail beyond the {snapshot["confidence"]:.0%} VaR cutoff, the estimated average one-day loss is <b>${tail:,.2f}</b>.</div>')
        section("Portfolio composition", "NORMALISED ALLOCATION")
        composition = pd.DataFrame({"Asset": snapshot["tickers"], "Allocation (%)": [w * 100 for w in snapshot["weights"]], "Allocated value (USD)": [w * snapshot["value"] for w in snapshot["weights"]]})
        st.dataframe(composition, hide_index=True, width="stretch", column_config={"Allocation (%)": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=100), "Allocated value (USD)": st.column_config.NumberColumn(format="$%.2f")})
    with tabs[1]:
        section("A distribution of possibilities", f"{snapshot['paths']:,} PATHS · {snapshot['horizon']} TRADING DAYS")
        result = results["simulation"]
        if "error" in result:
            st.error(result["error"])
        else:
            data = result["data"]
            st.plotly_chart(plot_monte_carlo_fan_chart(data["trajectories"], snapshot["value"]), width="stretch", config=chart_config)
            for col, label, key in zip(st.columns(2), ["Simulated value at risk", "Simulated expected shortfall"], ["mc_var_dollar", "mc_cvar_dollar"]):
                with col:
                    st.metric(label, f"${data[key]:,.2f}")
            st.caption("Correlated arithmetic-return simulation. Bands show the 10th–90th percentiles across simulated paths.")
            if snapshot["paths"] < 10000:
                st.caption("The path count is reduced at longer horizons to keep hosted responses manageable.")
    with tabs[2]:
        section("The risk–return trade-off", "LONG-ONLY · FULLY INVESTED")
        result = results["optimisation"]
        if "error" in result:
            st.error(result["error"])
        else:
            data = result["data"]
            portfolios = data["portfolios"]
            if data["efficient_frontier"]:
                st.plotly_chart(plot_efficient_frontier(data["efficient_frontier"], portfolios["max_sharpe"], portfolios["min_variance"]), width="stretch", config=chart_config)
            else:
                st.warning("No efficient frontier points were found for these assets.")
            for col, key, title in zip(st.columns(2), ["max_sharpe", "min_variance"], ["Maximum Sharpe", "Minimum variance"]):
                with col:
                    portfolio = portfolios[key]
                    section(title, f"SHARPE {portfolio['sharpe_ratio']:.2f}")
                    a, b = st.columns(2)
                    a.metric("Annualised return", f"{portfolio['return']:.2%}")
                    b.metric("Annualised volatility", f"{portfolio['volatility']:.2%}")
                    st.dataframe(pd.DataFrame({"Asset": list(portfolio["weights"]), "Weight (%)": [w * 100 for w in portfolio["weights"].values()]}), hide_index=True, width="stretch", column_config={"Weight (%)": st.column_config.NumberColumn(format="%.2f%%")})
            st.caption("Estimated from historical returns. Annual risk-free rate: 2%. These are model estimates, not guaranteed future returns.")
    with tabs[3]:
        section("Resilience under pressure", "HISTORICAL CRISIS REPLAY")
        result = results["stress"]
        if "error" in result:
            st.error(result["error"])
        else:
            good = {}
            for key, item in result["data"].items():
                if item.get("status") == "Success":
                    good[key] = item
                else:
                    st.warning(f"{item.get('scenario_name', key)}: {item.get('note', 'Historical data unavailable')}")
            if good:
                st.plotly_chart(plot_stress_test_drawdowns(good), width="stretch", config=chart_config)
                for col, item in zip(st.columns(len(good)), good.values()):
                    with col:
                        st.metric(item["scenario_name"], f"{item['max_drawdown_pct']:.1%}", f"${item['dollar_loss']:,.0f} loss equivalent", delta_color="off")
                st.caption("Maximum peak-to-trough drawdown within each crisis window, applied to the initial portfolio value for a loss equivalent.")

markup('<div class="q-footer"><span>QUANT / PORTFOLIO INTELLIGENCE</span><span>HISTORICAL DATA · MODEL-BASED ANALYTICS · USD</span></div>')
