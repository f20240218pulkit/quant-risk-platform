"""Long-only next-open execution shared by every strategy."""
from dataclasses import dataclass
import math

import numpy as np
import pandas as pd
from scipy.optimize import brentq


@dataclass(frozen=True)
class Step:
    cash: float
    units: np.ndarray
    fees: float
    slippage: float
    turnover: float
    trades: np.ndarray


def rebalance(cash, units, prices, target, fee_bps, slippage_bps):
    prices, target, units = [np.asarray(x, dtype=float) for x in (prices, target, units)]
    if (not np.isfinite([cash, fee_bps, slippage_bps]).all() or cash < 0 or
        not 0 <= fee_bps <= 100 or not 0 <= slippage_bps <= 100):
        raise ValueError("Cash and costs must be within supported bounds.")
    if (prices.shape != units.shape or target.shape != prices.shape or
        not np.isfinite([target, units, prices]).all() or (prices <= 0).any() or
        (units < 0).any() or (target < 0).any() or target.sum() > 1 + 1e-10):
        raise ValueError("Targets must be finite, long-only and sum to no more than 100%.")
    if target.sum() > 1:
        target = target / target.sum()
    old = units * prices
    equity = float(cash + old.sum())
    if equity <= 0:
        raise ValueError("Portfolio equity must be positive.")
    fee_rate, slip = fee_bps / 10_000, slippage_bps / 10_000

    def trade_cost(net_equity):
        trades = target * net_equity - old
        fill_notional = np.abs(trades) * (1 + np.sign(trades) * slip)
        return trades, float(fee_rate * fill_notional.sum()), float(slip * np.abs(trades).sum())

    def reserve(net_equity):
        _, fee, slip_cost = trade_cost(net_equity)
        return net_equity + fee + slip_cost - equity

    net = brentq(reserve, 0, equity, xtol=1e-13, rtol=1e-14)
    trades, fee, slip_cost = trade_cost(net)
    final_cash = cash - float(trades.sum()) - fee - slip_cost
    if final_cash < -max(1e-9, equity * 1e-12):
        raise ValueError("Execution could not reconcile available cash.")
    return Step(max(0., final_cash), target * net / prices, fee, slip_cost,
                float(np.abs(trades).sum() / equity), trades)


def simulate(data, targets, start, *, initial_cash=10000., fee_bps=10., slippage_bps=5.):
    if not 1 <= start < len(data.opens):
        raise ValueError("Execution must start after a decision session.")
    if not math.isfinite(initial_cash) or not 0 < initial_cash <= 1e9:
        raise ValueError("Initial cash must be in (0, 1 billion].")
    cash = initial_cash
    units = np.zeros(data.opens.shape[1])
    previous = initial_cash
    equity, ledger = [], []
    for index in range(start, len(data.opens)):
        session = data.opens.index[index]
        opening, close = data.opens.iloc[index].to_numpy(), data.closes.iloc[index].to_numpy()
        if callable(targets):
            old_marks = units * data.closes.iloc[index - 1].to_numpy()
            target = targets(index - 1, old_marks / (cash + old_marks.sum()), cash / (cash + old_marks.sum()))
        else:
            target = targets.get(index - 1)
        if target is not None:
            fill = rebalance(cash, units, opening, target, fee_bps, slippage_bps)
            cash, units = fill.cash, fill.units
            for symbol, amount, reference in zip(data.opens.columns, fill.trades, opening, strict=True):
                if abs(amount) <= 1e-10:
                    continue
                fill_price = reference * (1 + np.sign(amount) * slippage_bps / 10000)
                fill_notional = abs(amount / reference) * fill_price
                ledger.append({
                    "decision_at": data.cutoffs[index - 1].isoformat(), "fill_session": str(session.date()),
                    "instrument": symbol, "units_delta": float(amount / reference), "fill_price": float(fill_price),
                    "fee": float(fill_notional * fee_bps / 10000),
                    "slippage": float(abs(amount) * slippage_bps / 10000),
                    "turnover": abs(float(amount)) * fill.turnover / float(np.abs(fill.trades).sum()),
                })
        marked = float(cash + units @ close)
        if not math.isfinite(marked) or marked <= 0:
            raise ValueError("Execution could not mark a finite, positive portfolio value.")
        equity.append({"session": session, "equity": marked, "return": marked / previous - 1,
                       "cash": float(cash), **{f"weight:{s}": float(q*p/marked)
                        for s,q,p in zip(data.opens.columns, units, close, strict=True)}})
        previous = marked
    return pd.DataFrame(equity).set_index("session"), ledger


def performance(frame, ledger, initial_cash):
    values = frame["equity"]
    daily = frame["return"]
    volatility = daily.std(ddof=0)
    downside = np.sqrt(np.mean(np.square(np.minimum(daily, 0))))
    peak = values.cummax().clip(lower=initial_cash)
    growth = float(values.iloc[-1] / initial_cash)
    return {
        "period_return": growth - 1, "volatility": float(volatility * np.sqrt(252)),
        "cagr": float(np.expm1(np.log(growth) * 252 / len(values))),
        "sharpe": float(daily.mean() / volatility * np.sqrt(252)) if volatility else None,
        "sortino": float(daily.mean() / downside * np.sqrt(252)) if downside else None,
        "max_drawdown": float((values / peak - 1).min()),
        "turnover": sum(t["turnover"] for t in ledger),
        "fees": sum(t["fee"] for t in ledger), "slippage": sum(t["slippage"] for t in ledger),
    }
