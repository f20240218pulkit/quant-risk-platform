"""Claim and publish synthetic reports in a short PostgreSQL transaction."""
import argparse
import json
import logging
import os
import time
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from .database import database_engine, scope
from .service import query
from .valuation import aud_review

LOGGER = logging.getLogger(__name__)


def run_one(engine):
    with engine.begin() as connection:
        job = query(connection, """
            SELECT id, import_id, workspace_id, attempts FROM product_jobs
            WHERE state = 'queued' AND available_at <= now() ORDER BY available_at, id
            LIMIT 1 FOR UPDATE SKIP LOCKED
        """).mappings().one_or_none()
        if job is None:
            return False
        scope(connection, job["workspace_id"])
        draft = query(connection, """
            SELECT snapshot_date, positions FROM product_imports
            WHERE id = :id AND workspace_id = :workspace AND confirmed_at IS NOT NULL
        """, id=job["import_id"], workspace=job["workspace_id"]).mappings().one_or_none()
        attempts = job["attempts"] + 1
        try:
            if draft is None:
                raise ValueError("Confirmed import is unavailable.")
            with connection.begin_nested():
                report = aud_review(draft["snapshot_date"].isoformat(), draft["positions"])
                query(connection, """
                    INSERT INTO product_reports (id, workspace_id, import_id, snapshot_date, evidence)
                    VALUES (:report, :workspace, :import_id, :snapshot_date, CAST(:evidence AS jsonb))
                    ON CONFLICT (import_id) DO NOTHING
                """, report=str(uuid4()), workspace=job["workspace_id"], import_id=job["import_id"],
                    snapshot_date=draft["snapshot_date"], evidence=json.dumps(report))
        except (ValueError, KeyError, ArithmeticError, SQLAlchemyError):
            LOGGER.warning("Synthetic review job %s could not publish (attempt %d)", job["id"], attempts)
            query(connection, """
                UPDATE product_jobs SET state = :state, attempts = :attempts,
                    available_at = now() + :delay * interval '1 second' WHERE id = :id
            """, state="failed" if attempts == 3 else "queued", id=job["id"], attempts=attempts,
                delay=2 ** attempts)
        else:
            query(connection, "UPDATE product_jobs SET state = 'complete', attempts = :attempts WHERE id = :id",
                  id=job["id"], attempts=attempts)
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    options = parser.parse_args()
    if os.environ.get("WORKBENCH_DEMO_MODE") != "1":
        parser.error("The fixture worker requires WORKBENCH_DEMO_MODE=1.")
    logging.basicConfig(level=logging.INFO)
    engine = database_engine()
    try:
        if options.once:
            run_one(engine)
            return
        while True:
            try:
                if not run_one(engine):
                    time.sleep(1)
            except SQLAlchemyError as error:
                LOGGER.warning("Worker database temporarily unavailable (%s)", type(error).__name__)
                time.sleep(2)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
