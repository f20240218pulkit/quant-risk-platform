"""Consistent chart styling for the portfolio analytics workspace."""
import numpy as np
import plotly.graph_objects as go

GOLD = "#d6b777"
TEAL = "#70cbb5"
ROSE = "#e69b9b"
MUTED = "#8c9bb0"


def _style(fig, height=420):
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#111a26", plot_bgcolor="#111a26",
        font=dict(family="Inter, Arial, sans-serif", color=MUTED, size=12),
        height=height, margin=dict(l=25, r=25, t=58, b=35),
        hovermode="x unified", hoverlabel=dict(bgcolor="#1b283a", font_color="#edf2f7"),
        legend=dict(orientation="h", yanchor="bottom", y=1.05, x=0, font_size=11),
    )
    fig.update_xaxes(gridcolor="#1e2a3a", zeroline=False, showline=False, title_font_size=11, automargin=True)
    fig.update_yaxes(gridcolor="#263245", zeroline=False, showline=False, title_font_size=11, automargin=True)
    return fig


def plot_monte_carlo_fan_chart(trajectories, initial_value, percentiles=None):
    matrix = np.asarray(trajectories, dtype=float)
    if percentiles is None:
        p10, p50, p90 = np.percentile(matrix, [10, 50, 90], axis=0)
    else:
        p10, p50, p90 = (percentiles[key] for key in ("p10", "p50", "p90"))
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=p90, mode="lines", line=dict(width=0), name="90th percentile", hovertemplate="$%{y:,.0f}<extra>90th percentile</extra>"))
    fig.add_trace(go.Scatter(y=p10, mode="lines", line=dict(width=0), fill="tonexty", fillcolor="rgba(112,203,181,0.12)", name="10th–90th percentile", hovertemplate="$%{y:,.0f}<extra>10th percentile</extra>"))
    for path in matrix[:20]:
        fig.add_trace(go.Scatter(y=path, mode="lines", line=dict(color="rgba(140,155,176,0.13)", width=1), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(y=p50, mode="lines", name="Median outcome", line=dict(color=GOLD, width=2.5), hovertemplate="$%{y:,.0f}<extra>Median</extra>"))
    fig.add_hline(y=initial_value, line_color="#59677b", line_dash="dot", line_width=1)
    fig.update_layout(xaxis_title="Trading days", yaxis_title="Portfolio value · USD")
    fig.update_yaxes(tickprefix="$", tickformat=",.0f")
    return _style(fig)


def plot_efficient_frontier(frontier_points, max_sharpe, min_var):
    fig = go.Figure()
    if frontier_points:
        fig.add_trace(go.Scatter(x=[p["volatility"]*100 for p in frontier_points], y=[p["return"]*100 for p in frontier_points], mode="lines", name="Efficient frontier", line=dict(color=GOLD, width=2.5), hovertemplate="Risk %{x:.2f}% · Return %{y:.2f}%<extra>Efficient frontier</extra>"))
    for portfolio, name, color, symbol in [(max_sharpe, "Maximum Sharpe", TEAL, "diamond"), (min_var, "Minimum variance", "#9aabe0", "circle")]:
        fig.add_trace(go.Scatter(x=[portfolio["volatility"]*100], y=[portfolio["return"]*100], mode="markers", name=name, marker=dict(color=color, size=13, symbol=symbol, line=dict(color="#111a26", width=2)), hovertemplate="Risk %{x:.2f}% · Return %{y:.2f}%<extra>"+name+"</extra>"))
    fig.update_layout(xaxis_title="Annualised volatility", yaxis_title="Annualised expected return")
    fig.update_xaxes(ticksuffix="%")
    fig.update_yaxes(ticksuffix="%")
    return _style(fig)


def plot_stress_test_drawdowns(stress_data):
    items = list(stress_data.values())
    short_names = {"2008 Great Financial Crisis": "2008 / Financial crisis", "2020 COVID-19 Liquidity Shock": "2020 / COVID shock", "2022 Tech & Rate Hike Sell-Off": "2022 / Rate-hike sell-off"}
    fig = go.Figure(go.Bar(
        y=[short_names.get(item["scenario_name"], item["scenario_name"]) for item in items],
        x=[abs(item["max_drawdown_pct"])*100 for item in items], orientation="h",
        marker=dict(color=["#d6b777", "#9aabe0", "#70cbb5"][:len(items)], cornerradius=5),
        text=[f"{abs(item['max_drawdown_pct']):.1%}" for item in items], textposition="outside", textfont=dict(color="#edf2f7", size=13),
        customdata=[item["dollar_loss"] for item in items],
        hovertemplate="%{y}<br>Drawdown %{x:.1f}%<br>Loss equivalent $%{customdata:,.0f}<extra></extra>",
    ))
    max_dd = max((abs(item["max_drawdown_pct"])*100 for item in items), default=0)
    fig.update_layout(xaxis_title="Peak-to-trough drawdown", showlegend=False, bargap=.6)
    fig.update_xaxes(range=[0, max(max_dd*1.25, 1)], ticksuffix="%")
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return _style(fig, height=350)
