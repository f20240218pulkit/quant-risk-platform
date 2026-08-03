import numpy as np
import pandas as pd
import scipy.optimize as sco
from typing import Dict, List, Tuple, Union, Optional

TRADING_DAYS_PER_YEAR = 252

def calculate_portfolio_performance(
    weights: np.ndarray,
    mean_returns: pd.Series,
    cov_matrix: pd.DataFrame,
    risk_free_rate: float = 0.02
) -> Tuple[float, float, float]:
    """
    Calculates annualized return, annualized volatility, and Sharpe ratio 
    for a given set of portfolio weights.
    """
    # Annualized portfolio return
    annual_return = np.sum(mean_returns * weights) * TRADING_DAYS_PER_YEAR
    
    # Annualized portfolio volatility (standard deviation)
    annual_volatility = np.sqrt(
        np.dot(weights.T, np.dot(cov_matrix * TRADING_DAYS_PER_YEAR, weights))
    )
    
    # Sharpe Ratio: (Return - Risk-Free Rate) / Volatility
    sharpe_ratio = (annual_return - risk_free_rate) / annual_volatility
    
    return annual_return, annual_volatility, sharpe_ratio

def _neg_sharpe_ratio(
    weights: np.ndarray,
    mean_returns: pd.Series,
    cov_matrix: pd.DataFrame,
    risk_free_rate: float
) -> float:
    """Objective function to minimize (negative Sharpe ratio)."""
    return -calculate_portfolio_performance(weights, mean_returns, cov_matrix, risk_free_rate)[2]

def _portfolio_volatility(
    weights: np.ndarray,
    mean_returns: pd.Series,
    cov_matrix: pd.DataFrame,
    risk_free_rate: float
) -> float:
    """Objective function to minimize (portfolio volatility)."""
    return calculate_portfolio_performance(weights, mean_returns, cov_matrix, risk_free_rate)[1]

def optimize_portfolio(
    returns: pd.DataFrame,
    risk_free_rate: float = 0.02
) -> Dict[str, Union[Dict[str, float], np.ndarray]]:
    """
    Solves for Maximum Sharpe Ratio and Global Minimum Variance (GMV) portfolios.
    Enforces long-only constraints (weights sum to 1, no short selling).
    """
    mean_returns = returns.mean()
    cov_matrix = returns.cov()
    num_assets = len(mean_returns)
    tickers = list(returns.columns)
    
    # Equal weight initial guess and bounds (0% to 100% per asset)
    initial_weights = np.array([1.0 / num_assets] * num_assets)
    bounds = tuple((0.0, 1.0) for _ in range(num_assets))
    
    # Constraint: sum(weights) == 1
    constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0})
    
    # 1. Maximize Sharpe Ratio
    max_sharpe_result = sco.minimize(
        _neg_sharpe_ratio,
        initial_weights,
        args=(mean_returns, cov_matrix, risk_free_rate),
        method='SLSQP',
        bounds=bounds,
        constraints=constraints
    )
    
    max_sharpe_weights = max_sharpe_result.x
    ms_ret, ms_vol, ms_sharpe = calculate_portfolio_performance(
        max_sharpe_weights, mean_returns, cov_matrix, risk_free_rate
    )
    
    # 2. Minimize Volatility (Global Minimum Variance)
    min_vol_result = sco.minimize(
        _portfolio_volatility,
        initial_weights,
        args=(mean_returns, cov_matrix, risk_free_rate),
        method='SLSQP',
        bounds=bounds,
        constraints=constraints
    )
    
    min_vol_weights = min_vol_result.x
    mv_ret, mv_vol, mv_sharpe = calculate_portfolio_performance(
        min_vol_weights, mean_returns, cov_matrix, risk_free_rate
    )
    
    return {
        "max_sharpe": {
            "return": float(ms_ret),
            "volatility": float(ms_vol),
            "sharpe_ratio": float(ms_sharpe),
            "weights": {ticker: float(w) for ticker, w in zip(tickers, max_sharpe_weights)}
        },
        "min_variance": {
            "return": float(mv_ret),
            "volatility": float(mv_vol),
            "sharpe_ratio": float(mv_sharpe),
            "weights": {ticker: float(w) for ticker, w in zip(tickers, min_vol_weights)}
        }
    }

def generate_efficient_frontier(
    returns: pd.DataFrame,
    n_points: int = 50,
    risk_free_rate: float = 0.02
) -> List[Dict[str, float]]:
    """
    Generates target returns along the Markowitz Efficient Frontier curve.
    """
    mean_returns = returns.mean()
    cov_matrix = returns.cov()
    num_assets = len(mean_returns)
    
    initial_weights = np.array([1.0 / num_assets] * num_assets)
    bounds = tuple((0.0, 1.0) for _ in range(num_assets))
    
    # Find min and max achievable returns
    optimization_res = optimize_portfolio(returns, risk_free_rate)
    min_ret = optimization_res["min_variance"]["return"]
    max_ret = np.max(mean_returns) * TRADING_DAYS_PER_YEAR
    
    target_returns = np.linspace(min_ret, max_ret, n_points)
    frontier_points = []
    
    for target in target_returns:
        # Constraints: sum(weights) == 1 AND expected return == target return
        constraints = (
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},
            {'type': 'eq', 'fun': lambda w: (np.sum(mean_returns * w) * TRADING_DAYS_PER_YEAR) - target}
        )
        
        result = sco.minimize(
            _portfolio_volatility,
            initial_weights,
            args=(mean_returns, cov_matrix, risk_free_rate),
            method='SLSQP',
            bounds=bounds,
            constraints=constraints
        )
        
        if result.success:
            vol = result.fun
            sharpe = (target - risk_free_rate) / vol
            frontier_points.append({
                "return": float(target),
                "volatility": float(vol),
                "sharpe_ratio": float(sharpe)
            })
            
    return frontier_points

if __name__ == "__main__":
    import sys
    from pathlib import Path
    
    # Path resolution for standalone module execution
    root_dir = Path(__file__).resolve().parent.parent.parent
    if str(root_dir) not in sys.path:
        sys.path.append(str(root_dir))
        
    from src.core.data_loader import fetch_portfolio_data
    
    test_tickers = ["AAPL", "MSFT", "NVDA", "SPY", "GLD"]
    print(f"Fetching data for Markowitz Optimization on: {', '.join(test_tickers)}...")
    _, returns_df = fetch_portfolio_data(test_tickers, start_date="2022-01-01")
    
    print("\nRunning Scipy SLSQP Optimization Solver...")
    opt_results = optimize_portfolio(returns_df, risk_free_rate=0.02)
    
    ms = opt_results["max_sharpe"]
    mv = opt_results["min_variance"]
    
    print("\n--- MAXIMUM SHARPE RATIO PORTFOLIO ---")
    print(f"Annual Expected Return: {ms['return']*100:.2f}%")
    print(f"Annual Volatility:      {ms['volatility']*100:.2f}%")
    print(f"Sharpe Ratio:           {ms['sharpe_ratio']:.2f}")
    print("Optimal Weights:")
    for ticker, weight in ms['weights'].items():
        print(f"  - {ticker}: {weight*100:.1f}%")
        
    print("\n--- GLOBAL MINIMUM VARIANCE (GMV) PORTFOLIO ---")
    print(f"Annual Expected Return: {mv['return']*100:.2f}%")
    print(f"Annual Volatility:      {mv['volatility']*100:.2f}%")
    print(f"Sharpe Ratio:           {mv['sharpe_ratio']:.2f}")
    
    print("\nGenerating Efficient Frontier curve points...")
    frontier = generate_efficient_frontier(returns_df, n_points=5)
    print(f"Successfully calculated {len(frontier)} curve boundary coordinates.")