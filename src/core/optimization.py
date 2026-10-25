"""Long-only optimisation with explicit solver and constraint checks."""
import numpy as np
import scipy.optimize as sco

from src.core.validation import validate_returns

TRADING_DAYS_PER_YEAR = 252


class OptimizationError(ValueError):
    pass


def calculate_portfolio_performance(weights, mean_returns, cov_matrix, risk_free_rate=0.02):
    annual_return = float(np.dot(np.asarray(mean_returns), weights) * TRADING_DAYS_PER_YEAR)
    variance = float(weights @ (np.asarray(cov_matrix) * TRADING_DAYS_PER_YEAR) @ weights)
    volatility = float(np.sqrt(max(variance, 0)))
    if volatility <= 1e-12:
        raise OptimizationError("Sharpe optimisation requires non-zero portfolio volatility.")
    return annual_return, volatility, (annual_return - risk_free_rate) / volatility


def _setup(returns, risk_free_rate, cash_weight):
    validate_returns(returns)
    if not np.isfinite(risk_free_rate) or risk_free_rate < 0:
        raise ValueError("Risk-free rate must be finite and non-negative.")
    if not np.isfinite(cash_weight) or not 0 <= cash_weight < 1:
        raise ValueError("Optimisation requires cash weight below 100%.")
    n = returns.shape[1]
    return returns.mean(), returns.cov(), np.full(n, 1 / n), tuple((0., 1.) for _ in range(n))


def _verified(result, performance, target=None):
    weights = np.asarray(result.x, dtype=float)
    if (not result.success or not np.isfinite(weights).all()
            or abs(weights.sum() - 1) > 1e-6
            or (weights < -1e-7).any() or (weights > 1 + 1e-7).any()):
        raise OptimizationError("Solver did not produce a feasible, converged allocation.")
    metrics = performance(weights)
    if not np.isfinite(metrics).all() or (target is not None and abs(metrics[0] - target) > 1e-6):
        raise OptimizationError("Solver output failed numerical validation.")
    return weights, metrics


def optimize_portfolio(returns, risk_free_rate=0.02, cash_weight=0.0):
    mean, covariance, initial, bounds = _setup(returns, risk_free_rate, cash_weight)
    invested = 1 - cash_weight
    performance = lambda w: calculate_portfolio_performance(w * invested, mean, covariance, risk_free_rate)
    constraint = {'type': 'eq', 'fun': lambda w: w.sum() - 1}
    output = {}
    # One asset has an exact feasible allocation; SLSQP is unnecessary.
    for key, metric in [("max_sharpe", 2), ("min_variance", 1)]:
        if len(initial) == 1:
            weights, metrics = initial, performance(initial)
        else:
            result = sco.minimize(lambda w: -performance(w)[2] if metric == 2 else performance(w)[1],
                initial, method="SLSQP", bounds=bounds, constraints=constraint,
                options={"ftol": 1e-10, "maxiter": 500})
            weights, metrics = _verified(result, performance)
        output[key] = {
            "return": float(metrics[0]), "volatility": float(metrics[1]), "sharpe_ratio": float(metrics[2]),
            "weights": {ticker: float(w * invested) for ticker, w in zip(returns.columns, weights)},
            "cash_weight": cash_weight,
        }
    return output


def generate_efficient_frontier(returns, n_points=50, risk_free_rate=0.02, cash_weight=0.0):
    mean, covariance, initial, bounds = _setup(returns, risk_free_rate, cash_weight)
    invested = 1 - cash_weight
    performance = lambda w: calculate_portfolio_performance(w * invested, mean, covariance, risk_free_rate)
    optimum = optimize_portfolio(returns, risk_free_rate, cash_weight)
    if len(initial) == 1:
        item = optimum["min_variance"]
        return [{k: item[k] for k in ("return", "volatility", "sharpe_ratio")}]
    target_returns = np.linspace(optimum["min_variance"]["return"], float(mean.max() * 252 * invested), n_points)
    frontier = []
    for target in target_returns:
        constraints = ({'type': 'eq', 'fun': lambda w: w.sum() - 1},
                       {'type': 'eq', 'fun': lambda w, target=target: performance(w)[0] - target})
        result = sco.minimize(lambda w: performance(w)[1], initial, method="SLSQP",
            bounds=bounds, constraints=constraints, options={"ftol": 1e-10, "maxiter": 500})
        try:
            _, metrics = _verified(result, performance, target)
        except OptimizationError:
            continue
        frontier.append(dict(zip(("return", "volatility", "sharpe_ratio"), map(float, metrics))))
    return frontier
