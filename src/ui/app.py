import streamlit as st
import requests
import pandas as pd
import sys
import os
from pathlib import Path

# Add project root path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from src.ui.components.charts import (
    plot_monte_carlo_fan_chart,
    plot_efficient_frontier,
    plot_stress_test_drawdowns
)

# Override for Docker or another backend using an environment variable.
API_BASE_URL = os.environ.get(
    "API_BASE_URL", "https://quant-risk-platform-iu77-beta.vercel.app"
).strip().rstrip("/")


def request_analysis(endpoint, payload):
    """Show useful failures without stopping the other dashboard tabs."""
    try:
        response = requests.post(
            f"{API_BASE_URL}{endpoint}", json=payload, timeout=(10, 120)
        )
        try:
            result = response.json()
        except ValueError:
            st.error(f"The analytics service returned HTTP {response.status_code} without JSON. Please retry.")
            return {}
        if not response.ok:
            st.error(f"Analytics request failed (HTTP {response.status_code}).")
            st.write(result.get("detail", result) if isinstance(result, dict) else result)
            return {}
        if not isinstance(result, dict) or result.get("status") != "success":
            st.error("The analytics service could not complete this request.")
            return {}
        return result
    except requests.Timeout:
        st.error("The analytics service took too long. Please retry or use fewer assets.")
    except requests.RequestException:
        st.error("Cannot reach the analytics service. Please retry shortly.")
    return {}


st.set_page_config(
    page_title="Quant Risk Platform",
    page_icon="📈",
    layout="wide"
)

st.title("📈 Quantitative Risk & Portfolio Intelligence Platform")
st.markdown("*Portfolio risk analysis, correlated simulations, and Modern Portfolio Theory optimization.*")

# Sidebar Configuration
st.sidebar.header("⚙️ Portfolio Configuration")

tickers_input = st.sidebar.text_input("Tickers (comma separated)", "AAPL, MSFT, NVDA, SPY, GLD")
portfolio_val = st.sidebar.number_input("Portfolio Value ($)", value=100000.0, min_value=1.0, step=5000.0)
conf_level = st.sidebar.slider("Confidence Level", min_value=0.90, max_value=0.99, value=0.95, step=0.01)
horizon_days = st.sidebar.slider("Forecast Horizon (Days)", min_value=1, max_value=60, value=10)

tickers = [t.strip().upper() for t in tickers_input.split(",") if t.strip()]
if not tickers:
    st.info("Enter at least one asset ticker to continue.")
    st.stop()
if len(tickers) != len(set(tickers)):
    st.error("Please enter each ticker only once.")
    st.stop()
num_assets = len(tickers)

st.sidebar.subheader("Asset Allocations (%)")
weights = []
for i, ticker in enumerate(tickers):
    default_w = round(100.0 / num_assets, 1)
    w = st.sidebar.number_input(f"{ticker} Weight %", value=default_w, min_value=0.0, max_value=100.0, key=f"weight_{ticker}")
    weights.append(w / 100.0)

# Normalize weights if sum != 1
total_w = sum(weights)
if total_w > 0:
    weights = [w / total_w for w in weights]
else:
    st.error("Give at least one asset a weight greater than zero.")
    st.stop()

# Keep trajectory responses small enough for the hosted API.
simulation_paths = min(10000, 120000 // (horizon_days + 1))

# Check backend health
@st.cache_data(ttl=5)
def check_api_health():
    try:
        r = requests.get(f"{API_BASE_URL}/", timeout=(10, 30))
        return r.status_code == 200 and r.json().get("status") == "online"
    except (requests.RequestException, ValueError, AttributeError):
        return False

if not check_api_health():
    st.error("The analytics service is temporarily unavailable. Please reload in a moment.")
    st.stop()

# Dashboard Action Button
if st.button("🚀 Run Portfolio Analysis", type="primary"):
    
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Downside Risk Metrics", 
        "🎲 Monte Carlo Stochastics", 
        "🎯 Efficient Frontier", 
        "💥 Crisis Stress Testing"
    ])
    
    # TAB 1: DOWNSIDE RISK METRICS
    with tab1:
        st.subheader("Downside Risk Analytics")
        payload = {
            "tickers": tickers,
            "weights": weights,
            "portfolio_value": portfolio_val,
            "confidence_level": conf_level
        }
        res = request_analysis("/api/v1/risk", payload)
        
        if res.get("status") == "success":
            data = res["data"]
            col1, col2, col3 = st.columns(3)
            
            p_var = data["parametric_var"]
            h_var = data["historical_var"]
            cvar = data["cvar_expected_shortfall"]
            
            col1.metric("Parametric VaR", f"${p_var['var_dollar']:,.2f}", f"-{p_var['var_pct']*100:.2f}%")
            col2.metric("Historical VaR", f"${h_var['var_dollar']:,.2f}", f"-{h_var['var_pct']*100:.2f}%")
            col3.metric("Expected Shortfall (CVaR)", f"${cvar['cvar_dollar']:,.2f}", f"-{cvar['cvar_pct']*100:.2f}%")
            
            st.info(f"💡 **Expected Shortfall Interpretation:** Given a drawdown breaches your {conf_level*100:.0f}% 1-day VaR threshold, your average expected tail loss is **${cvar['cvar_dollar']:,.2f}**.")
            
    # TAB 2: MONTE CARLO STOCHASTICS
    with tab2:
        st.subheader(f"{simulation_paths:,}-Path Correlated Return Simulation")
        if simulation_paths < 10000:
            st.caption("Longer horizons use fewer paths to keep the hosted response manageable.")
        mc_payload = {
            "tickers": tickers,
            "weights": weights,
            "portfolio_value": portfolio_val,
            "days": horizon_days,
            "n_simulations": simulation_paths,
            "confidence_level": conf_level
        }
        res = request_analysis("/api/v1/monte-carlo", mc_payload)
        
        if res.get("status") == "success":
            mc_data = res["data"]
            st.plotly_chart(
                plot_monte_carlo_fan_chart(mc_data["trajectories"], portfolio_val), 
                use_container_width=True
            )
            
            col1, col2 = st.columns(2)
            col1.metric(f"{horizon_days}-Day Monte Carlo VaR", f"${mc_data['mc_var_dollar']:,.2f}")
            col2.metric(f"{horizon_days}-Day Monte Carlo CVaR", f"${mc_data['mc_cvar_dollar']:,.2f}")

    # TAB 3: PORTFOLIO OPTIMIZATION
    with tab3:
        st.subheader("Modern Portfolio Theory Optimization")
        opt_payload = {"tickers": tickers, "risk_free_rate": 0.02}
        res = request_analysis("/api/v1/optimize", opt_payload)
        
        if res.get("status") == "success":
            opt_data = res["data"]
            portfolios = opt_data["portfolios"]
            frontier = opt_data["efficient_frontier"]
            
            if frontier:
                st.plotly_chart(
                    plot_efficient_frontier(frontier, portfolios["max_sharpe"], portfolios["min_variance"]),
                    use_container_width=True
                )
            else:
                st.warning("No efficient frontier points were found for these assets.")
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("### 🌟 Maximum Sharpe Portfolio")
                ms = portfolios["max_sharpe"]
                st.write(f"**Annual Return:** {ms['return']*100:.2f}%")
                st.write(f"**Annual Volatility:** {ms['volatility']*100:.2f}%")
                st.write(f"**Sharpe Ratio:** {ms['sharpe_ratio']:.2f}")
                st.dataframe(pd.DataFrame([(asset, weight * 100) for asset, weight in ms["weights"].items()], columns=["Asset", "Weight %"]))
                
            with col2:
                st.markdown("### 🛡️ Global Minimum Variance Portfolio")
                mv = portfolios["min_variance"]
                st.write(f"**Annual Return:** {mv['return']*100:.2f}%")
                st.write(f"**Annual Volatility:** {mv['volatility']*100:.2f}%")
                st.write(f"**Sharpe Ratio:** {mv['sharpe_ratio']:.2f}")
                st.dataframe(pd.DataFrame([(asset, weight * 100) for asset, weight in mv["weights"].items()], columns=["Asset", "Weight %"]))

    # TAB 4: CRISIS STRESS TESTING
    with tab4:
        st.subheader("Macro Shock Replay")
        stress_payload = {"tickers": tickers, "weights": weights, "portfolio_value": portfolio_val}
        res = request_analysis("/api/v1/stress-test", stress_payload)
        
        if res.get("status") == "success":
            stress_data = res["data"]
            valid_scenarios = {}
            for key, info in stress_data.items():
                if info.get("status") == "Success":
                    valid_scenarios[key] = info
                else:
                    st.warning(f"{info.get('scenario_name', key)}: {info.get('note', info.get('status', 'Unavailable'))}")
            if valid_scenarios:
                st.plotly_chart(plot_stress_test_drawdowns(valid_scenarios), use_container_width=True)
