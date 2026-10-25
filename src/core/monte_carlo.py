"""Correlated lognormal asset simulation with explicit portfolio semantics."""
import numpy as np

from src.core.validation import allocation, risk_inputs, validate_returns

MODEL_VERSION = "lognormal-fixed-holdings-v1"
MAX_SIMULATION_CELLS = 5_000_000


def run_monte_carlo_simulation(returns, weights, portfolio_value=100000.0,
        days=1, n_simulations=10000, confidence_level=0.95, seed=42, cash_weight=0.0):
    validate_returns(returns)
    risk_inputs(returns.iloc[:, 0], portfolio_value, confidence_level)
    if not isinstance(days, int) or not 1 <= days <= 252:
        raise ValueError("Simulation horizon must be 1 to 252 trading days.")
    if not isinstance(n_simulations, int) or not 101 <= n_simulations <= 50000:
        raise ValueError("Simulation paths must be 101 to 50,000.")
    if n_simulations * days * returns.shape[1] > MAX_SIMULATION_CELLS:
        raise ValueError("Simulation workload exceeds 5,000,000 asset-day-path cells.")
    weights = allocation(weights, returns.shape[1], cash_weight)
    # Fit the mean and covariance of daily log increments directly. No second
    # -sigma^2/2 correction is applied to an already estimated log-return mean.
    logs = np.log1p(returns.to_numpy(dtype=float))
    covariance = np.atleast_2d(np.cov(logs, rowvar=False, ddof=1))
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    if eigenvalues.min() < -1e-10:
        raise ValueError("Log-return covariance is not positive semidefinite.")
    factor = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0)))
    rng = np.random.default_rng(seed)
    trajectories = np.empty((n_simulations, days + 1))
    trajectories[:, 0] = portfolio_value
    asset_growth = np.ones((n_simulations, len(weights)))
    for day in range(1, days + 1):
        increments = logs.mean(axis=0) + rng.standard_normal(asset_growth.shape) @ factor.T
        asset_growth *= np.exp(increments)
        trajectories[:, day] = portfolio_value * (asset_growth @ weights + cash_weight)
    if not np.isfinite(trajectories).all():
        raise ValueError("Simulation produced non-finite values; reduce the horizon or review the data.")
    terminal = trajectories[:, -1]
    pnl = terminal - portfolio_value
    cutoff = np.quantile(pnl, 1 - confidence_level, method="linear")
    var = float(-cutoff)
    cvar = float(-pnl[pnl <= cutoff].mean())
    p10, p50, p90 = np.percentile(trajectories, [10, 50, 90], axis=0)
    return {
        "mc_var_dollar": var, "mc_var_pct": var / portfolio_value,
        "mc_cvar_dollar": cvar, "mc_cvar_pct": cvar / portfolio_value,
        "mean_terminal_value": float(terminal.mean()),
        "median_terminal_value": float(np.median(terminal)),
        "trajectories": trajectories,
        "percentiles": {"p10": p10.tolist(), "p50": p50.tolist(), "p90": p90.tolist()},
        "model_version": MODEL_VERSION, "seed": seed, "n_simulations": n_simulations,
        "cash_weight": cash_weight, "rebalancing": "fixed_holdings",
    }


def compact_simulation(result, max_paths=100):
    """Metrics and bands use ALL paths. Only illustrative paths are sampled."""
    output = dict(result)
    paths = output.pop("trajectories")
    indices = np.linspace(0, len(paths) - 1, min(max_paths, len(paths)), dtype=int)
    output["trajectories"] = paths[indices].tolist()
    output["returned_paths"] = len(indices)
    output["trajectory_sample"] = True
    return output
