"""Shared numerical contracts. No provider, UI, or persistence dependencies."""
import numpy as np
import pandas as pd


class DataQualityError(ValueError):
    """Inputs cannot support the requested analysis without inventing data."""


def clean_tickers(tickers):
    result = [str(t).strip().upper() for t in tickers]
    if not result or len(result) > 50 or any(not t or len(t) > 32 for t in result):
        raise ValueError("Provide between 1 and 50 non-empty tickers (up to 32 characters each).")
    if len(set(result)) != len(result):
        raise ValueError("Duplicate tickers must be reconciled before analysis.")
    return result


def allocation(weights, n_assets, cash_weight=0.0):
    """Legacy weights are relative within the invested sleeve; cash is explicit."""
    values = np.asarray(weights, dtype=float)
    if values.shape != (n_assets,) or not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("Provide one finite, non-negative weight per asset.")
    if not np.isfinite(cash_weight) or not 0 <= cash_weight <= 1:
        raise ValueError("Cash weight must be between zero and one.")
    total = values.sum()
    if not np.isfinite(total) or total <= 0:
        raise ValueError("Asset weights must have a finite, positive total.")
    return values / total * (1 - cash_weight)


def validate_returns(returns, min_observations=2):
    if not isinstance(returns, pd.DataFrame) or returns.shape[1] == 0:
        raise DataQualityError("Expected a non-empty asset return table.")
    if returns.columns.has_duplicates or returns.index.has_duplicates or not returns.index.is_monotonic_increasing:
        raise DataQualityError("Return identifiers and dates must be unique and ordered.")
    values = returns.to_numpy(dtype=float)
    if len(values) < min_observations or not np.isfinite(values).all():
        raise DataQualityError(f"Require at least {min_observations} complete, finite return observations.")
    if (values <= -1).any():
        raise DataQualityError("Asset returns must be greater than -100%.")
    return returns


def risk_inputs(returns, portfolio_value, confidence_level):
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.isfinite(values).all():
        raise ValueError("Require at least two finite portfolio return observations.")
    if not np.isfinite(portfolio_value) or portfolio_value <= 0:
        raise ValueError("Portfolio value must be finite and positive.")
    if not np.isfinite(confidence_level) or not 0 < confidence_level < 1:
        raise ValueError("Confidence must be strictly between zero and one.")
    return values
