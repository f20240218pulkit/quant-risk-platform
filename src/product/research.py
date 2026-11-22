"""Opt-in, fixed synthetic research presets using the existing engine."""
from functools import lru_cache
from threading import Lock

from src.workbench.demo import demo_research
from src.workbench.experiments import ExperimentConfig, experiment_report, run_experiment
from src.workbench.research_data import parse_research_data

_lock = Lock()


@lru_cache(maxsize=2)
def _run(ppo):
    bars, news = demo_research()
    config = ExperimentConfig(ppo=ppo)
    data = parse_research_data(bars, news)
    return experiment_report(run_experiment(data, config), config)


def synthetic_experiment(ppo):
    # Serialize first computation of each deterministic preset.
    with _lock:
        return _run(ppo)
