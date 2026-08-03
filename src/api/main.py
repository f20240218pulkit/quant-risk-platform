import sys
from pathlib import Path

# Add project root directory to sys.path for clean core imports
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.append(str(root_dir))

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import numpy as np

# Core Math Imports
from src.core.data_loader import fetch_portfolio_data
from src.core.var_engine import run_risk_suite
from src.core.monte_carlo import run_monte_carlo_simulation
from src.core.optimization import optimize_portfolio, generate_efficient_frontier
from src.core.stress_testing import run_stress_test

# Schema Imports
from src.api.schemas import (
    RiskAnalysisRequest,
    MonteCarloRequest,
    OptimizationRequest,
    StressTestRequest
)

# Initialize FastAPI App
app = FastAPI(
    title="Quantitative Risk & Portfolio Intelligence API",
    description="Institutional-grade REST microservice for multi-asset risk analytics, stochastic simulations, and portfolio optimization.",
    version="1.0.0"
)

# Enable CORS (Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Health Check"])
async def root():
    return {
        "status": "online",
        "service": "Quant Risk Platform Microservice",
        "version": "1.0.0"
    }

@app.post("/api/v1/risk", tags=["Risk Analytics"])
async def calculate_portfolio_risk(payload: RiskAnalysisRequest):
    """
    Computes Parametric VaR, Historical VaR, and Conditional VaR (Expected Shortfall).
    """
    try:
        _, returns_df = fetch_portfolio_data(payload.tickers, start_date=payload.start_date)
        
        # Calculate daily weighted portfolio return series
        normalized_weights = np.array(payload.weights) / np.sum(payload.weights)
        portfolio_daily_returns = returns_df.dot(normalized_weights)
        
        # Compute risk metrics across all 3 methodologies
        results = run_risk_suite(
            returns=portfolio_daily_returns,
            portfolio_value=payload.portfolio_value,
            confidence_level=payload.confidence_level
        )
        return {"status": "success", "data": results}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate risk suite: {str(e)}"
        )

@app.post("/api/v1/monte-carlo", tags=["Stochastic Simulations"])
async def simulate_monte_carlo(payload: MonteCarloRequest):
    """
    Runs 10,000+ Geometric Brownian Motion trajectories using Cholesky Decomposition.
    """
    try:
        _, returns_df = fetch_portfolio_data(payload.tickers, start_date=payload.start_date)
        
        sim_results = run_monte_carlo_simulation(
            returns=returns_df,
            weights=payload.weights,
            portfolio_value=payload.portfolio_value,
            days=payload.days,
            n_simulations=payload.n_simulations,
            confidence_level=payload.confidence_level
        )
        
        # Convert NumPy trajectories matrix to nested Python list for JSON response
        sim_results["trajectories"] = sim_results["trajectories"].tolist()
        
        return {"status": "success", "data": sim_results}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Monte Carlo simulation failed: {str(e)}"
        )

@app.post("/api/v1/optimize", tags=["Portfolio Optimization"])
async def run_portfolio_optimization(payload: OptimizationRequest):
    """
    Solves for Maximum Sharpe Ratio, GMV weights, and Markowitz Efficient Frontier curve.
    """
    try:
        _, returns_df = fetch_portfolio_data(payload.tickers, start_date=payload.start_date)
        
        optimization_results = optimize_portfolio(returns_df, risk_free_rate=payload.risk_free_rate)
        frontier_points = generate_efficient_frontier(returns_df, n_points=30, risk_free_rate=payload.risk_free_rate)
        
        return {
            "status": "success", 
            "data": {
                "portfolios": optimization_results,
                "efficient_frontier": frontier_points
            }
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Portfolio optimization failed: {str(e)}"
        )

@app.post("/api/v1/stress-test", tags=["Crisis Stress Testing"])
async def run_macro_stress_tests(payload: StressTestRequest):
    """
    Replays 2008 GFC, 2020 COVID, and 2022 Inflation shocks on current holdings.
    """
    try:
        results = run_stress_test(payload.tickers, payload.weights, payload.portfolio_value)
        return {"status": "success", "data": results}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Stress testing scenario failed: {str(e)}"
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True)