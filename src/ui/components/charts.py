import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import List, Dict, Any

def plot_monte_carlo_fan_chart(trajectories: List[List[float]], initial_value: float) -> go.Figure:
    """Renders 10,000 Monte Carlo price paths with quantile bands."""
    matrix = np.array(trajectories)
    days = matrix.shape[1] - 1
    
    p10 = np.percentile(matrix, 10, axis=0)
    p50 = np.percentile(matrix, 50, axis=0)
    p90 = np.percentile(matrix, 90, axis=0)
    
    fig = go.Figure()
    
    for i in range(min(50, matrix.shape[0])):
        fig.add_trace(go.Scatter(
            y=matrix[i],
            mode='lines',
            line=dict(color='rgba(100, 100, 255, 0.05)', width=1),
            showlegend=False,
            hoverinfo='skip'
        ))
        
    fig.add_trace(go.Scatter(
        y=p50, mode='lines', name='Median Path (50th %ile)',
        line=dict(color='#00F0FF', width=3)
    ))
    fig.add_trace(go.Scatter(
        y=p90, mode='lines', name='Bull Case (90th %ile)',
        line=dict(color='#00FF87', width=2, dash='dash')
    ))
    fig.add_trace(go.Scatter(
        y=p10, mode='lines', name='Bear Case (10th %ile)',
        line=dict(color='#FF2E93', width=2, dash='dash')
    ))
    
    fig.update_layout(
        title=f"Stochastic Price Forecast ({days}-Day Horizon)",
        xaxis_title="Trading Days",
        yaxis_title="Portfolio Value ($)",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

def plot_efficient_frontier(
    frontier_points: List[Dict[str, float]], 
    max_sharpe: Dict[str, Any], 
    min_var: Dict[str, Any]
) -> go.Figure:
    """Renders Markowitz Efficient Frontier curve with optimal allocation markers."""
    df_frontier = pd.DataFrame(frontier_points)
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=df_frontier['volatility'] * 100,
        y=df_frontier['return'] * 100,
        mode='lines',
        name='Efficient Frontier',
        line=dict(color='#00F0FF', width=3)
    ))
    fig.add_trace(go.Scatter(
        x=[max_sharpe['volatility'] * 100],
        y=[max_sharpe['return'] * 100],
        mode='markers',
        name='Max Sharpe Ratio',
        marker=dict(color='#00FF87', size=14, symbol='star')
    ))
    fig.add_trace(go.Scatter(
        x=[min_var['volatility'] * 100],
        y=[min_var['return'] * 100],
        mode='markers',
        name='Global Min Variance',
        marker=dict(color='#FFD700', size=12, symbol='diamond')
    ))
    
    fig.update_layout(
        title="Markowitz Efficient Frontier Curve",
        xaxis_title="Annualized Risk / Volatility (%)",
        yaxis_title="Annualized Expected Return (%)",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig

def plot_stress_test_drawdowns(stress_data: Dict[str, Dict[str, Any]]) -> go.Figure:
    """Renders historical crisis drawdown bar comparisons."""
    scenarios = []
    drawdowns = []
    dollar_losses = []
    
    for key, info in stress_data.items():
        scenarios.append(info["scenario_name"])
        drawdowns.append(abs(info["max_drawdown_pct"]) * 100)
        dollar_losses.append(info["dollar_loss"])
        
    fig = go.Figure(data=[
        go.Bar(
            x=scenarios,
            y=drawdowns,
            text=[f"-{dd:.1f}% (-${dl:,.0f})" for dd, dl in zip(drawdowns, dollar_losses)],
            textposition='auto',
            marker_color='#FF2E93'
        )
    ])
    
    fig.update_layout(
        title="Historical Macro Shock Drawdown Analysis",
        xaxis_title="Crisis Scenario",
        yaxis_title="Peak-to-Trough Drawdown (%)",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20)
    )
    return fig