"""Lease jobs and publish immutable reviews with fenced completion."""
import argparse
from datetime import date
import json
import logging
import os
import time
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine, scope
from .market import configured_market, synthetic_market
from .service import query
from .valuation import aud_review
from .workflows import evaluate_crossings, plan_refreshes

LOGGER = logging.getLogger(__name__)


def claim(engine, lease_seconds=45):
    token = str(uuid4())
    with engine.begin() as connection:
        query(connection, """
            UPDATE product_jobs SET state='failed', lease_token=NULL, lease_until=NULL
            WHERE state='running' AND attempts=3 AND lease_until <= now()
        """)
        row = query(connection, """
            WITH picked AS (
                SELECT id FROM product_jobs
                WHERE attempts < 3 AND ((state='queued' AND available_at <= now())
                  OR (state='running' AND lease_until <= now()))
                ORDER BY available_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE product_jobs j SET state='running', attempts=j.attempts+1,
                lease_token=:token, lease_until=now() + :duration * interval '1 second'
            FROM picked WHERE j.id=picked.id
            RETURNING j.id, j.import_id, j.workspace_id, j.attempts, j.lease_token
        """, token=token, duration=lease_seconds).mappings().one_or_none()
        return dict(row) if row else None


def load_draft(connection, job):
    scope(connection, job["workspace_id"])
    draft = query(connection, """
        SELECT snapshot_date, holdings_date, positions FROM product_imports
        WHERE id=:id AND workspace_id=:workspace AND confirmed_at IS NOT NULL
    """, id=job["import_id"], workspace=job["workspace_id"]).mappings().one_or_none()
    if draft is None:
        raise ValueError("Confirmed import is unavailable.")
    return dict(draft)


def finish(engine, job, report):
    with engine.begin() as connection:
        valid = query(connection, """
            SELECT id FROM product_jobs WHERE id=:id AND lease_token=:token
                AND state='running' AND lease_until > now() FOR UPDATE
        """, id=job["id"], token=job["lease_token"]).scalar_one_or_none()
        if valid is None:
            return False
        scope(connection, job["workspace_id"])
        if report is not None:
            published = query(connection, """
                INSERT INTO product_reports (id,workspace_id,import_id,snapshot_date,evidence)
                VALUES (:report,:workspace,:import_id,:day,CAST(:evidence AS jsonb))
                ON CONFLICT (import_id) DO NOTHING RETURNING id
            """, report=str(uuid4()), workspace=job["workspace_id"], import_id=job["import_id"],
                day=report["snapshot_date"], evidence=json.dumps(report)).scalar_one_or_none()
            if published:
                evaluate_crossings(connection, job["workspace_id"], report)
        state = "complete" if report is not None else "failed" if job["attempts"] == 3 else "queued"
        query(connection, """
            UPDATE product_jobs SET state=:state, lease_token=NULL, lease_until=NULL,
                available_at=now() + :delay * interval '1 second' WHERE id=:id
        """, id=job["id"], state=state, delay=2 ** job["attempts"] if state == "queued" else 0)
        return True


def run_one(engine, market=None):
    market = market or synthetic_market()
    job = claim(engine)
    if job is None:
        return False
    try:
        with engine.begin() as connection:
            draft = load_draft(connection, job)
        day = draft["snapshot_date"].isoformat()
        report = aud_review(day, draft["positions"],
                            holdings_date=(draft["holdings_date"] or draft["snapshot_date"]).isoformat(),
                            **market.review_inputs(day))
    except (ValueError, KeyError, ArithmeticError):
        LOGGER.warning("Review job %s could not publish (attempt %d)", job["id"], job["attempts"])
        report = None
    finish(engine, job, report)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    options = parser.parse_args()
    market = configured_market(os.environ.get("WORKBENCH_DEMO_MODE") == "1")
    logging.basicConfig(level=logging.INFO)
    engine = database_engine()
    try:
        if options.once:
            run_one(engine, market)
            return
        next_schedule = 0.0
        while True:
            try:
                if time.monotonic() >= next_schedule:
                    eligible = market.eligible_dates()
                    if eligible:
                        plan_refreshes(engine, date.fromisoformat(eligible[-1]))
                    next_schedule = time.monotonic() + 30
                if not run_one(engine, market):
                    time.sleep(1)
            except SQLAlchemyError as error:
                LOGGER.warning("Worker database temporarily unavailable (%s)", type(error).__name__)
                time.sleep(2)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
