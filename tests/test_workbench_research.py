from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from src.workbench.demo import demo_research
from src.workbench.execution import rebalance, simulate
from src.workbench.experiments import ExperimentConfig, experiment_report, run_experiment
from src.workbench.research_data import news_features, parse_research_data


def test_rebalance_reserves_fees_and_slippage_from_cash():
    fill = rebalance(1000., [0], [10], [1], 100, 100)
    assert fill.units[0] == pytest.approx(1000 / (10 * 1.01**2))
    assert fill.cash == pytest.approx(0)
    assert fill.units[0] * 10 + fill.cash + fill.fees + fill.slippage == pytest.approx(1000)


def test_buy_does_not_capture_prior_price_gap():
    bars, _ = demo_research()
    data = parse_research_data(bars)
    opens, closes = data.opens.copy(), data.closes.copy()
    opens.iloc[60, 0], closes.iloc[60, 0] = 120, 132
    closes.iloc[59, 0] = 100
    frame, ledger = simulate(replace(data, opens=opens, closes=closes), {59: [1, 0, 0]}, 60,
                             initial_cash=1000, fee_bps=0, slippage_bps=0)
    assert frame.iloc[0]["equity"] == pytest.approx(1100)
    assert ledger[0]["fill_price"] == 120
    assert ledger[0]["decision_at"] == data.cutoffs[59].isoformat()


def test_late_neutral_news_has_coverage_only_on_next_decision():
    bars, news = demo_research()
    data = parse_research_data(bars, news)
    column = data.closes.columns.get_loc("XNAS:ALFA")
    features = news_features(data)
    assert features[0, column].tolist() == [0, 0]
    assert features[1, column].tolist() == pytest.approx([0, np.log(2)])
    assert not data.news.empty


def test_matched_ablation_and_two_seed_ppo_are_reproducible():
    data = parse_research_data(*demo_research())
    config = ExperimentConfig(ppo=True)
    first = experiment_report(run_experiment(data, config), config)
    second = experiment_report(run_experiment(data, config), config)
    assert first == second
    assert len([name for name in first["runs"] if name.startswith("PPO")]) == 4
    assert first["runs"]["Cash"]["metrics"]["period_return"] == 0
    assert first["ablation"]["net_return_delta_by_window"]
    for fold in first["folds"]:
        assert fold["last_training_outcome_session"] < fold["decision_at"][:10]
    json.dumps(first, allow_nan=False)


def test_without_news_ablation_is_unavailable():
    bars, _ = demo_research()
    result = run_experiment(parse_research_data(bars))
    assert result["ablation"] is None
    assert "Price + sentiment ridge" not in result["runs"]
