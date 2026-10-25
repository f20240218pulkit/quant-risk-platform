import numpy as np
import scipy.stats as stats
import pandas as pd
from src.core.validation import risk_inputs
from typing import Dict, Union

def calculate_parametric_var(
    returns: Union[pd.Series, np.ndarray], 
    portfolio_value: float = 10000.0, 
    confidence_level: float = 0.95
) -> Dict[str, float]:
    """
    Calculates Parametric (Variance-Covariance) Value at Risk.
    """
    returns = risk_inputs(returns, portfolio_value, confidence_level)
    mean_return = np.mean(returns)
    std_dev = np.std(returns)
    
    # Quantile for normal distribution
    z_score = stats.norm.ppf(confidence_level)
    
    # 1-day Parametric VaR percentage and dollar loss
    var_pct = (z_score * std_dev) - mean_return
    var_dollar = portfolio_value * var_pct
    
    return {
        "var_pct": float(var_pct),
        "var_dollar": float(var_dollar)
    }

def calculate_historical_var(
    returns: Union[pd.Series, np.ndarray], 
    portfolio_value: float = 10000.0, 
    confidence_level: float = 0.95
) -> Dict[str, float]:
    """
    Calculates Historical Simulation Value at Risk using empirical percentiles.
    """
    returns = risk_inputs(returns, portfolio_value, confidence_level)
    # Convert confidence level to lower tail percentile (e.g., 95% conf -> 5th percentile)
    percentile = (1 - confidence_level) * 100
    var_pct = -np.percentile(returns, percentile, method="linear")
    var_dollar = portfolio_value * var_pct
    
    return {
        "var_pct": float(var_pct),
        "var_dollar": float(var_dollar)
    }

def calculate_cvar(
    returns: Union[pd.Series, np.ndarray], 
    portfolio_value: float = 10000.0, 
    confidence_level: float = 0.95
) -> Dict[str, float]:
    """
    Calculates Conditional VaR (Expected Shortfall) - the expected tail loss beyond VaR.
    """
    returns = risk_inputs(returns, portfolio_value, confidence_level)
    percentile = (1 - confidence_level) * 100
    var_pct_threshold = np.percentile(returns, percentile, method="linear")
    
    # Filter returns that are worse than the VaR cutoff line
    tail_losses = returns[returns <= var_pct_threshold]
    
    cvar_pct = -np.mean(tail_losses)
    cvar_dollar = portfolio_value * cvar_pct
    
    return {
        "cvar_pct": float(cvar_pct),
        "cvar_dollar": float(cvar_dollar)
    }

def run_risk_suite(
    returns: Union[pd.Series, np.ndarray], 
    portfolio_value: float = 10000.0, 
    confidence_level: float = 0.95
) -> Dict[str, Dict[str, float]]:
    """
    Executes the full downside risk analytical suite across all methodologies.
    """
    parametric = calculate_parametric_var(returns, portfolio_value, confidence_level)
    historical = calculate_historical_var(returns, portfolio_value, confidence_level)
    cvar = calculate_cvar(returns, portfolio_value, confidence_level)
    
    return {
        "parametric_var": parametric,
        "historical_var": historical,
        "cvar_expected_shortfall": cvar
    }

if __name__ == "__main__":
    # Internal Unit Test with synthetic daily returns
    np.random.seed(42)
    # Simulate 1,000 daily returns with mean=0.05% and standard deviation=2%
    simulated_returns = np.random.normal(0.0005, 0.02, 1000)
    
    portfolio = 100000.0  # $100,000 portfolio
    conf = 0.95
    
    results = run_risk_suite(simulated_returns, portfolio_value=portfolio, confidence_level=conf)
    
    print(f"--- QUANT RISK SUITE REPORT (${portfolio:,.2f} Portfolio | {conf*100}% Conf) ---")
    print(f"Parametric VaR:         ${results['parametric_var']['var_dollar']:,.2f} ({results['parametric_var']['var_pct']*100:.2f}%)")
    print(f"Historical VaR:         ${results['historical_var']['var_dollar']:,.2f} ({results['historical_var']['var_pct']*100:.2f}%)")
    print(f"Expected Shortfall (CVaR): ${results['cvar_expected_shortfall']['cvar_dollar']:,.2f} ({results['cvar_expected_shortfall']['cvar_pct']*100:.2f}%)")