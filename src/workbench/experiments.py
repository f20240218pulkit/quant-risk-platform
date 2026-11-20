"""Matched walk-forward comparisons and a bounded NumPy PPO research experiment."""
from dataclasses import dataclass
import json

import numpy as np
import pandas as pd

from src.workbench.execution import performance, rebalance, simulate
from src.workbench.research_data import news_features


@dataclass(frozen=True)
class ExperimentConfig:
    fee_bps: float = 10
    slippage_bps: float = 5
    cash_weight: float = .1
    rebalance_sessions: int = 5
    initial_cash: float = 10_000
    ppo: bool = False

    def __post_init__(self):
        if not (0 <= self.fee_bps <= 100 and 0 <= self.slippage_bps <= 100
                and 0 <= self.cash_weight < 1 and isinstance(self.rebalance_sessions, int)
                and 1 <= self.rebalance_sessions <= 60
                and 0 < self.initial_cash <= 1e9):
            raise ValueError("Experiment settings are outside the supported limits.")


def _price_features(closes):
    recent = closes.pct_change(fill_method=None)
    return np.stack((recent.to_numpy(),
                     closes.pct_change(5, fill_method=None).to_numpy(),
                     closes.pct_change(20, fill_method=None).to_numpy(),
                     recent.rolling(10).std(ddof=0).to_numpy()), axis=-1)


def _ridge_predict(past, outcome, query):
    center = past.mean(axis=0)
    spread = past.std(axis=0)
    spread = np.where(spread > 1e-10, spread, 1)
    normalized = (past - center) / spread
    y_mean = float(outcome.mean())
    coefficients = np.linalg.solve(normalized.T @ normalized + 2 * np.eye(normalized.shape[1]),
                                   normalized.T @ (outcome - y_mean))
    return y_mean + ((query - center) / spread) @ coefficients


def _rank_allocation(scores, invested):
    # Stable ranks spread the invested sleeve over the top half of the universe.
    order = np.argsort(-scores, kind="stable")[:max(1, (len(scores) + 1) // 2)]
    target = np.zeros(len(scores))
    target[order] = invested / len(order)
    return target


def _softmax(values):
    exp = np.exp(values - max(values))
    return exp / exp.sum()


def _train_ppo(data, features, end, seed, config):
    """Gaussian policy over logits, clipped objective, linear value baseline.

    The first out-of-sample decision index is end. Training stops before it and
    consumes only earlier fills and marks. The cash logit is an explicit action.
    """
    rng = np.random.default_rng(seed)
    early = features[20:end]
    center = early.mean(axis=(0, 1))
    scale = np.maximum(early.std(axis=(0, 1)), 1e-6)
    normalized = np.clip((features - center) / scale, -8, 8)
    n = features.shape[1]

    def state(index, weights, current_cash):
        return np.r_[normalized[index].ravel(), weights, current_cash, 1.]

    policy = np.zeros((len(state(20, np.zeros(n), 1.0)), n + 1))
    sigma = .45
    training_steps = range(20, end - 1, config.rebalance_sessions)
    if len(training_steps) < 3:
        raise ValueError("PPO needs at least three training rebalances. Shorten the interval or provide longer history.")
    for _ in range(6):
        states, actions, rewards = [], [], []
        cash, units, previous = config.initial_cash, np.zeros(n), config.initial_cash
        for index in training_steps:
            old = units * data.closes.iloc[index].to_numpy()
            equity = cash + old.sum()
            states.append(state(index, old / equity, cash / equity))
            actions.append(states[-1] @ policy + rng.normal(0, sigma, n + 1))
            target = (1 - config.cash_weight) * _softmax(actions[-1])[:-1]
            fill = rebalance(cash, units, data.opens.iloc[index + 1].to_numpy(), target,
                             config.fee_bps, config.slippage_bps)
            cash, units = fill.cash, fill.units
            mark_index = min(end - 1, index + config.rebalance_sessions)
            marked = float(cash + units @ data.closes.iloc[mark_index].to_numpy())
            rewards.append(np.log(marked / previous))
            previous = marked
        x, actions = np.asarray(states), np.asarray(actions)
        discounted = np.empty(len(rewards))
        running = 0.
        for j in reversed(range(len(rewards))):
            running = rewards[j] + .97 * running
            discounted[j] = running
        critic = np.linalg.solve(x.T @ x + .5 * np.eye(x.shape[1]), x.T @ discounted)
        advantage = discounted - x @ critic
        advantage = (advantage - advantage.mean()) / max(advantage.std(), 1e-8)
        old_logp = -np.square(actions - x @ policy).sum(axis=1) / (2 * sigma**2)
        for _ in range(4):
            difference = actions - x @ policy
            logp = -np.square(difference).sum(axis=1) / (2 * sigma**2)
            ratio = np.exp(np.clip(logp - old_logp, -20, 20))
            active = np.where(advantage >= 0, ratio <= 1.2, ratio >= .8)
            gradient = x.T @ ((active * ratio * advantage)[:, None] * difference / sigma**2) / len(x)
            policy += .008 * gradient / max(1., np.linalg.norm(gradient))

    def decide(index, weights, current_cash):
        if (index - end) % config.rebalance_sessions:
            return None
        return (1 - config.cash_weight) * _softmax(state(index, weights, current_cash) @ policy)[:-1]

    return decide


def run_experiment(data, config=ExperimentConfig()):
    total, assets = data.opens.shape
    if total < 100 or assets == 0:
        raise ValueError("Research requires at least 100 sessions and one instrument.")
    if config.ppo and (total > 600 or assets > 8):
        raise ValueError("PPO supports at most 600 sessions and eight instruments per local run.")
    start = max(60, total // 2)
    features = _price_features(data.closes)
    sentiment = news_features(data)
    combined = np.concatenate((features, sentiment), axis=2)
    has_news = bool(sentiment[:total - 1, :, 1].sum())
    invested = 1 - config.cash_weight
    equal = np.full(assets, invested / assets)
    decisions = range(start - 1, total - 1, config.rebalance_sessions)
    targets = {"Cash": {}, "Buy and hold": {start - 1: equal},
               "Scheduled equal weight": {i: equal for i in decisions},
               "Momentum": {i: _rank_allocation(features[i, :, 2], invested) for i in decisions},
               "Price ridge": {}}
    if has_news:
        targets["Price + sentiment ridge"] = {}
    # At decision t, training labels end at open t-1 or earlier. The two-open
    # target for decision j matures at j+2, so a label at the boundary is purged.
    opened = data.opens.to_numpy()
    labels = opened[2:] / opened[1:-1] - 1
    folds = []
    for index in decisions:
        end = index - 2
        label_values = labels[20:end].reshape(-1)
        for name, inputs in [("Price ridge", features), ("Price + sentiment ridge", combined)]:
            if name in targets:
                p = inputs[20:end].reshape(-1, inputs.shape[-1])
                prediction = _ridge_predict(p, label_values, inputs[index])
                targets[name][index] = _rank_allocation(prediction, invested)
        folds.append({"decision_at": data.cutoffs[index].isoformat(),
                      "last_training_outcome_session": str(data.opens.index[index - 1].date())})
    if config.ppo:
        for seed in (7, 19):
            targets[f"PPO price features (seed {seed})"] = _train_ppo(data, features, start - 1, seed, config)
            if has_news:
                targets[f"PPO price + news (seed {seed})"] = _train_ppo(data, combined, start - 1, seed, config)

    runs = {}
    for name, allocation in targets.items():
        frame, ledger = simulate(data, allocation, start, initial_cash=config.initial_cash,
                                 fee_bps=config.fee_bps, slippage_bps=config.slippage_bps)
        runs[name] = {"frame": frame, "ledger": ledger,
                      "metrics": performance(frame, ledger, config.initial_cash)}
    ablation = None
    sensitivity = []
    if has_news:
        a, b = runs["Price ridge"]["metrics"], runs["Price + sentiment ridge"]["metrics"]
        ablation = {k: b[k] - a[k] for k in ("period_return", "max_drawdown", "fees", "turnover")}
        for multiplier in (0, 1, 2):
            fees = min(100., config.fee_bps * multiplier)
            slip = min(100., config.slippage_bps * multiplier)
            net = {}
            for name in ("Price ridge", "Price + sentiment ridge"):
                if multiplier == 1:
                    net[name] = runs[name]["metrics"]["period_return"]
                else:
                    replay, _ = simulate(data, targets[name], start, initial_cash=config.initial_cash,
                                         fee_bps=fees, slippage_bps=slip)
                    net[name] = float(replay["equity"].iloc[-1] / config.initial_cash - 1)
            sensitivity.append({"fee_bps": fees, "slippage_bps": slip, **net,
                                "sentiment_delta": net["Price + sentiment ridge"] - net["Price ridge"]})
        # Use compounded matched returns across contiguous, non-overlapping
        # reporting windows. Windows are descriptive, not independent trials.
        a_returns = runs["Price ridge"]["frame"]["return"]
        b_returns = runs["Price + sentiment ridge"]["frame"]["return"]
        ablation["net_return_delta_by_window"] = [
            {"start": str(a_returns.index[j].date()),
             "end": str(a_returns.index[min(j + 19, len(a_returns) - 1)].date()),
             "delta": float((1 + b_returns.iloc[j:j+20]).prod() - (1 + a_returns.iloc[j:j+20]).prod())}
            for j in range(0, len(a_returns), 20)
        ]
    return {"dataset_id": data.dataset_id, "score_source": data.score_source,
            "news_covered_asset_sessions": int(np.count_nonzero(sentiment[:, :, 1])),
            "total_asset_sessions": int(sentiment.shape[0] * sentiment.shape[1]), "runs": runs,
            "folds": folds, "ablation": ablation, "cost_sensitivity": sensitivity}


def experiment_report(result, config):
    from dataclasses import asdict
    payload = {k: v for k, v in result.items() if k != "runs"}
    payload["format"] = "portfolio-research-1"
    payload["settings"] = asdict(config)
    payload["runs"] = {
        name: {
            "metrics": run["metrics"], "ledger": run["ledger"],
            "daily": json.loads(run["frame"].reset_index().to_json(orient="records", date_format="iso")),
        }
        for name, run in result["runs"].items()
    }
    return payload
