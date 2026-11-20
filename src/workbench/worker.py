"""Process durable research and market refresh jobs from the same private database."""
import argparse
import base64
import os
import time

from src.workbench.experiments import ExperimentConfig, experiment_report, run_experiment
from src.workbench.market import prepare_market_review
from src.workbench.research_data import parse_research_data
from src.workbench.review import confirm_review, review_portfolio
from src.workbench.storage import Store


def process_one(store):
    job = store.claim()
    if job is None:
        return False
    try:
        payload = job["payload"]
        if job["kind"] == "research":
            bars = base64.b64decode(payload["bars"], validate=True)
            news = base64.b64decode(payload["news"], validate=True) if payload.get("news") else None
            config = ExperimentConfig(**payload["config"])
            result = experiment_report(run_experiment(parse_research_data(bars, news), config), config)
        elif job["kind"] == "refresh":
            prepared = prepare_market_review(base64.b64decode(payload["holdings"], validate=True),
                                             payload["cash"], payload["currency"])
            result, _ = review_portfolio(confirm_review(prepared))
        else:
            raise ValueError("Unsupported job.")
        store.finish(job, result)
    except ValueError as exc:
        # No raw row data or provider exception is placed in a durable job log.
        store.finish(job, {"error": "Job inputs or provider coverage did not pass validation."},
                     error=True, retry=job["kind"] == "refresh")
    except Exception:
        store.finish(job, {"error": "Job failed due to a processing or service error."},
                     error=True, retry=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.getenv("WORKBENCH_DB"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.db:
        parser.error("Provide --db or set WORKBENCH_DB.")
    store = Store(args.db)
    while True:
        worked = process_one(store)
        if args.once:
            break
        if not worked:
            time.sleep(3)


if __name__ == "__main__":
    main()
