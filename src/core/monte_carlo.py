import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Union

def run_monte_carlo_simulation(
    returns: pd.DataFrame,
    weights: Union[List[float], np.ndarray],
    portfolio_value: float = 100000.0,
    days: int = 1,
    n_simulations: int = 10000,
    confidence_level: float = 0.95,
    seed: int = 42
) -> Dict[str, Union[float, np.ndarray]]:
    """
    Executes a Multi-Asset Monte Carlo Simulation using Geometric Brownian Motion 
    with Cholesky Decomposition to preserve cross-asset correlation.
    
    Args:
        returns: DataFrame of historical daily returns for each asset.
        weights: List or Array of portfolio asset allocation weights (must sum to 1).
        portfolio_value: Total starting portfolio value in dollars.
        days: Forecasting time horizon in trading days (e.g., 1 day or 252 days).
        n_simulations: Number of Monte Carlo paths to generate (e.g., 10,000).
        confidence_level: VaR confidence threshold (e.g., 0.95).
        seed: Random seed for reproducibility.
        
    Returns:
        Dict containing VaR, CVaR, mean forecasted value, and full trajectory matrix.
    """
    np.random.seed(seed)
    weights = np.array(weights)
    
    # Ensure weights sum to 1.0
    weights = weights / np.sum(weights)
    
    # Calculate daily mean returns and covariance matrix
    mean_returns = returns.mean().values
    cov_matrix = returns.cov().values
    
    # Cholesky Decomposition: L * L^T = Covariance Matrix
    # Generates lower triangular matrix L for correlated random sampling
    try:
        cholesky_matrix = np.linalg.cholesky(cov_matrix)
    except np.linalg.LinAlgError:
        # If matrix is not positive-definite, add tiny regularizing constant to diagonal
        cov_matrix += np.eye(cov_matrix.shape[0]) * 1e-8
        cholesky_matrix = np.linalg.cholesky(cov_matrix)
        
    num_assets = len(weights)
    
    # Generate uncorrelated standard normal random numbers: (simulations, days, assets)
    uncorrelated_normals = np.random.normal(size=(n_simulations, days, num_assets))
    
    # Transform uncorrelated numbers into correlated samples using Cholesky L matrix
    # Shape: (simulations, days, assets)
    correlated_normals = np.einsum('ij, stj -> sti', cholesky_matrix, uncorrelated_normals)
    
    # Compute simulated daily returns using GBM drift and volatility
    # Daily return = mean + correlated_noise
    simulated_daily_returns = mean_returns + correlated_normals
    
    # Calculate portfolio daily returns by multiplying asset returns with asset weights
    # Shape: (simulations, days)
    portfolio_daily_returns = np.dot(simulated_daily_returns, weights)
    
    # Compute cumulative portfolio value trajectories across time horizon
    # Trajectories shape: (n_simulations, days + 1)
    trajectories = np.zeros((n_simulations, days + 1))
    trajectories[:, 0] = portfolio_value
    
    for t in range(1, days + 1):
        trajectories[:, t] = trajectories[:, t - 1] * (1 + portfolio_daily_returns[:, t - 1])
        
    # Terminal portfolio values at the end of the time horizon
    terminal_values = trajectories[:, -1]
    
    # Terminal dollar profit/loss distribution
    pnl_distribution = terminal_values - portfolio_value
    
    # Calculate Monte Carlo Value at Risk (VaR)
    percentile = (1 - confidence_level) * 100
    mc_var_dollar = -np.percentile(pnl_distribution, percentile)
    mc_var_pct = mc_var_dollar / portfolio_value
    
    # Calculate Monte Carlo Conditional VaR / Expected Shortfall (CVaR)
    var_cutoff = -mc_var_dollar
    tail_pnls = pnl_distribution[pnl_distribution <= var_cutoff]
    mc_cvar_dollar = -np.mean(tail_pnls) if len(tail_pnls) > 0 else mc_var_dollar
    mc_cvar_pct = mc_cvar_dollar / portfolio_value
    
    return {
        "mc_var_dollar": float(mc_var_dollar),
        "mc_var_pct": float(mc_var_pct),
        "mc_cvar_dollar": float(mc_cvar_dollar),
        "mc_cvar_pct": float(mc_cvar_pct),
        "mean_terminal_value": float(np.mean(terminal_values)),
        "median_terminal_value": float(np.median(terminal_values)),
        "trajectories": trajectories  # Matrix passed to Plotly in UI layer
    }


if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    # Add project root directory to sys.path
    root_dir = Path(__file__).resolve().parent.parent.parent
    if str(root_dir) not in sys.path:
        sys.path.append(str(root_dir))
        
    from src.core.data_loader import fetch_portfolio_data
    
    tickers = ["AAPL", "MSFT", "NVDA", "SPY", "GLD"]
    weights = [0.2, 0.2, 0.2, 0.2, 0.2]  # Equal weighting
    portfolio_val = 100000.0  # $100,000 investment
    sim_paths = 10000
    time_horizon_days = 10    # 10-day risk forecast
    conf = 0.95
    
    print(f"Fetching market data for Monte Carlo Engine...")
    _, returns_df = fetch_portfolio_data(tickers, start_date="2022-01-01")
    
    print(f"Running {sim_paths:,} Monte Carlo simulations ({time_horizon_days}-day horizon)...")
    results = run_monte_carlo_simulation(
        returns=returns_df,
        weights=weights,
        portfolio_value=portfolio_val,
        days=time_horizon_days,
        n_simulations=sim_paths,
        confidence_level=conf
    )
    
    print("\n--- MONTE CARLO RISK REPORT ---")
    print(f"Portfolio Initial Value:      ${portfolio_val:,.2f}")
    print(f"Expected Mean End Value:     ${results['mean_terminal_value']:,.2f}")
    print(f"{time_horizon_days}-Day Monte Carlo VaR ({conf*100}%):  ${results['mc_var_dollar']:,.2f} ({results['mc_var_pct']*100:.2f}%)")
    print(f"{time_horizon_days}-Day Monte Carlo CVaR ({conf*100}%): ${results['mc_cvar_dollar']:,.2f} ({results['mc_cvar_pct']*100:.2f}%)")