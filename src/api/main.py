"""Portfolio analytics API. Network/CPU handlers run in FastAPI's thread pool."""
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from src.api.schemas import (RiskAnalysisRequest, MonteCarloRequest,
    OptimizationRequest, StressTestRequest, ValuationRequest)
from src.core.data_loader import fetch_portfolio_data
from src.core.validation import DataQualityError, allocation, validate_returns
from src.core.var_engine import run_risk_suite
from src.core.monte_carlo import run_monte_carlo_simulation, compact_simulation
from src.core.optimization import optimize_portfolio, generate_efficient_frontier
from src.core.stress_testing import run_stress_test
from src.domain.portfolio import value_holdings

logger = logging.getLogger(__name__)
app = FastAPI(title="Quantitative Risk & Portfolio Intelligence API", version="1.1.0",
    description="Portfolio risk analytics with explicit cash, data-quality checks and model assumptions.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
    allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


def history(payload):
    prices, returns = fetch_portfolio_data(payload.tickers, start_date=payload.start_date.isoformat())
    # Defensive labelled join even if a provider adapter returns reordered data.
    missing = set(payload.tickers) - set(returns.columns)
    if missing:
        raise DataQualityError("Requested asset history is missing.")
    returns = returns.loc[:, payload.tickers]
    validate_returns(returns, min_observations=252)
    metadata = {
        "tickers": payload.tickers, "observations": len(returns),
        "observation_start": str(returns.index[0].date()),
        "observation_end": str(returns.index[-1].date()),
        "requested_start": payload.start_date.isoformat(),
        "price_policy": "provider_adjusted_close_no_filling",
        "cash_weight": payload.cash_weight,
        "cash_return_assumption": "zero_nominal_return",
        "engine_version": "1.1.0",
        "interpretation": "hypothetical_current_exposure_analysis_not_realised_account_performance",
    }
    return returns, metadata


def guarded(operation):
    try:
        return operation()
    except (DataQualityError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Analytics operation failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Market data or analytics processing is temporarily unavailable.") from exc


@app.get("/", tags=["Health Check"])
def root():
    return {"status": "online", "service": "Quant Risk Platform", "version": "1.1.0"}


@app.post("/api/v1/risk", tags=["Risk Analytics"])
def calculate_portfolio_risk(payload: RiskAnalysisRequest):
    def run():
        returns, metadata = history(payload)
        weights = allocation(payload.weights, len(payload.tickers), payload.cash_weight)
        results = run_risk_suite(returns.dot(weights), payload.portfolio_value, payload.confidence_level)
        metadata.update({"rebalancing": "constant_current_exposures_on_historical_daily_returns",
            "horizon_trading_days": 1, "confidence_level": payload.confidence_level,
            "quantile_method": "linear", "tail_selection": "observations_at_or_below_return_quantile"})
        return {"status": "success", "data": results, "metadata": metadata}
    return guarded(run)


@app.post("/api/v1/monte-carlo", tags=["Stochastic Simulations"])
def simulate_monte_carlo(payload: MonteCarloRequest):
    def run():
        returns, metadata = history(payload)
        result = run_monte_carlo_simulation(returns, payload.weights, payload.portfolio_value,
            payload.days, payload.n_simulations, payload.confidence_level, payload.seed, payload.cash_weight)
        metadata.update({"model_version": result["model_version"], "rebalancing": "fixed_holdings",
            "horizon_trading_days": payload.days, "confidence_level": payload.confidence_level})
        return {"status": "success", "data": compact_simulation(result), "metadata": metadata}
    return guarded(run)


@app.post("/api/v1/optimize", tags=["Portfolio Optimization"])
def run_portfolio_optimization(payload: OptimizationRequest):
    def run():
        returns, metadata = history(payload)
        portfolios = optimize_portfolio(returns, payload.risk_free_rate, payload.cash_weight)
        frontier = generate_efficient_frontier(returns, 30, payload.risk_free_rate, payload.cash_weight)
        metadata.update({"cash_allocation": "fixed", "risk_free_rate": payload.risk_free_rate,
            "annualisation_days": 252, "interpretation": "hypothetical_long_only_allocation"})
        return {"status": "success", "data": {"portfolios": portfolios, "efficient_frontier": frontier}, "metadata": metadata}
    return guarded(run)


@app.post("/api/v1/stress-test", tags=["Crisis Stress Testing"])
def run_macro_stress_tests(payload: StressTestRequest):
    return guarded(lambda: {"status": "success", "data": run_stress_test(payload.tickers,
        payload.weights, payload.portfolio_value, payload.cash_weight)})


@app.post("/api/v2/valuations", tags=["Portfolio Foundation"])
def create_valuation(payload: ValuationRequest):
    """Stateless valuation of explicitly supplied quotes; no quote verification or storage."""
    return guarded(lambda: {"status": "success", "data": value_holdings(payload.holdings, payload.quotes).model_dump(mode="json"),
        "metadata": {"quote_verification": "caller_supplied_unverified", "persistence": "none"}})
