"""Bounded API inputs shared by manual and future import workflows."""
from datetime import date
import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.validation import clean_tickers
from src.domain.portfolio import HoldingsSnapshot, Quote


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    tickers: list[str] = Field(min_length=1, max_length=50)
    start_date: date = date(2022, 1, 1)

    @field_validator("tickers")
    @classmethod
    def tickers_valid(cls, tickers):
        return clean_tickers(tickers)


class WeightedRequest(AnalysisRequest):
    weights: list[float] = Field(min_length=1, max_length=50)
    portfolio_value: float = Field(default=100000.0, gt=0, le=1e15)
    cash_weight: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def weights_valid(self):
        if len(self.weights) != len(self.tickers):
            raise ValueError("Provide one weight per ticker.")
        if any(w < 0 for w in self.weights) or not math.isfinite(sum(self.weights)) or sum(self.weights) <= 0:
            raise ValueError("Weights must be non-negative with a finite, positive total.")
        return self


class RiskAnalysisRequest(WeightedRequest):
    confidence_level: float = Field(default=0.95, gt=0, lt=1)


class MonteCarloRequest(RiskAnalysisRequest):
    days: int = Field(default=10, gt=0, le=252)
    n_simulations: int = Field(default=10000, gt=100, le=50000)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)

    @model_validator(mode="after")
    def workload(self):
        if self.days * self.n_simulations * len(self.tickers) > 5_000_000:
            raise ValueError("Reduce assets, paths or days: maximum 5,000,000 asset-day-path cells.")
        return self


class OptimizationRequest(AnalysisRequest):
    risk_free_rate: float = Field(default=0.02, ge=0, le=1)
    cash_weight: float = Field(default=0.0, ge=0, lt=1)


class StressTestRequest(WeightedRequest):
    pass


class ValuationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    holdings: HoldingsSnapshot
    quotes: tuple[Quote, ...] = Field(min_length=1, max_length=50)
