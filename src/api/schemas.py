from pydantic import BaseModel, Field
from typing import List, Optional

class RiskAnalysisRequest(BaseModel):
    tickers: List[str] = Field(..., example=["AAPL", "MSFT", "NVDA", "SPY"])
    weights: List[float] = Field(..., example=[0.25, 0.25, 0.25, 0.25])
    portfolio_value: float = Field(default=100000.0, gt=0, example=100000.0)
    confidence_level: float = Field(default=0.95, gt=0, lt=1, example=0.95)
    start_date: str = Field(default="2022-01-01", example="2022-01-01")

class MonteCarloRequest(BaseModel):
    tickers: List[str] = Field(..., example=["AAPL", "MSFT", "NVDA", "SPY"])
    weights: List[float] = Field(..., example=[0.25, 0.25, 0.25, 0.25])
    portfolio_value: float = Field(default=100000.0, gt=0, example=100000.0)
    days: int = Field(default=10, gt=0, le=252, example=10)
    n_simulations: int = Field(default=10000, gt=100, le=50000, example=10000)
    confidence_level: float = Field(default=0.95, gt=0, lt=1, example=0.95)
    start_date: str = Field(default="2022-01-01", example="2022-01-01")

class OptimizationRequest(BaseModel):
    tickers: List[str] = Field(..., example=["AAPL", "MSFT", "NVDA", "SPY", "GLD"])
    risk_free_rate: float = Field(default=0.02, ge=0, example=0.02)
    start_date: str = Field(default="2022-01-01", example="2022-01-01")

class StressTestRequest(BaseModel):
    tickers: List[str] = Field(..., example=["AAPL", "MSFT", "SPY", "GLD"])
    weights: List[float] = Field(..., example=[0.25, 0.25, 0.25, 0.25])
    portfolio_value: float = Field(default=100000.0, gt=0, example=100000.0)