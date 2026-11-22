"""Portfolio follow-up actions backed by workspace-scoped state."""
from datetime import date, timedelta
from decimal import Decimal, localcontext
from hashlib import sha256
import json
from uuid import uuid4

from .database import scope
from .service import confirm_import, query


def enqueue_refresh(connection, workspace_id, day):
    # Prefer a user-confirmed upload over a clone for any given target date.
    source = query(connection, """
        SELECT id, snapshot_date, input_hash, positions FROM product_imports
        WHERE workspace_id=:workspace AND NOT is_refresh AND confirmed_at IS NOT NULL
          AND snapshot_date <= :day
        ORDER BY snapshot_date DESC, confirmed_at DESC, id DESC LIMIT 1
    """, workspace=workspace_id, day=day).mappings().one_or_none()
    if source is None:
        return None
    draft_id = source["id"]
    if source["snapshot_date"] != day:
        digest = sha256(f"refresh:{source['id']}".encode()).hexdigest()
        draft_id = query(connection, """
            INSERT INTO product_imports
                (id, workspace_id, snapshot_date, holdings_date, is_refresh, input_hash, positions, issues)
            VALUES (:id, :workspace, :day, :holdings, true, :digest, CAST(:positions AS jsonb), '[]')
            ON CONFLICT (workspace_id, snapshot_date, input_hash) DO NOTHING RETURNING id
        """, id=str(uuid4()), workspace=workspace_id, day=day, holdings=source["snapshot_date"],
            digest=digest, positions=json.dumps(source["positions"])).scalar_one_or_none()
        if draft_id is None:
            draft_id = query(connection, """
                SELECT id FROM product_imports
                WHERE workspace_id=:workspace AND snapshot_date=:day AND input_hash=:digest
            """, workspace=workspace_id, day=day, digest=digest).scalar_one()
    return confirm_import(connection, workspace_id, draft_id)


def plan_refreshes(engine, day):
    with engine.begin() as connection:
        watchlist = query(connection, """
            SELECT workspace_id FROM product_refresh
            WHERE enabled AND (last_period IS NULL OR last_period < :day)
            ORDER BY last_period NULLS FIRST, workspace_id LIMIT 50 FOR UPDATE SKIP LOCKED
        """, day=day).scalars().all()
        for workspace_id in watchlist:
            scope(connection, workspace_id)
            enqueue_refresh(connection, workspace_id, day)
            query(connection, """
                UPDATE product_refresh SET last_period=:day WHERE workspace_id=:workspace
            """, day=day, workspace=workspace_id)


def rules(connection, workspace_id):
    return [dict(row) for row in query(connection, """
        SELECT id, instrument, threshold, last_date FROM product_rules
        WHERE workspace_id=:workspace ORDER BY instrument, threshold, id
    """, workspace=workspace_id).mappings()]


def add_rule(connection, workspace_id, instrument, threshold):
    query(connection, """
        INSERT INTO product_rules (id, workspace_id, instrument, threshold)
        VALUES (:id, :workspace, :instrument, :threshold)
        ON CONFLICT (workspace_id, instrument, threshold) DO NOTHING
    """, id=str(uuid4()), workspace=workspace_id, instrument=instrument, threshold=threshold)


def inbox(connection, workspace_id):
    return [dict(row) for row in query(connection, """
        SELECT a.id, a.snapshot_date, a.weight, a.acknowledged_at, r.instrument, r.threshold
        FROM product_alerts a JOIN product_rules r ON (a.workspace_id, a.rule_id)=(r.workspace_id,r.id)
        WHERE a.workspace_id=:workspace ORDER BY a.snapshot_date DESC, a.id LIMIT 100
    """, workspace=workspace_id).mappings()]


def evaluate_crossings(connection, workspace_id, report):
    day = date.fromisoformat(report["snapshot_date"])
    # An old upload can be repriced for inspection without driving alerts.
    if (report["status"] != "complete"
            or day - date.fromisoformat(report["holdings_date"]) > timedelta(days=7)):
        return
    positions = {row["instrument"]: Decimal(row["weight"]) * 100 for row in report["positions"]}
    watched = query(connection, """
        SELECT id, instrument, threshold, previously_above FROM product_rules
        WHERE workspace_id=:workspace AND (last_date IS NULL OR last_date < :day)
        ORDER BY id FOR UPDATE
    """, workspace=workspace_id, day=day).mappings().all()
    for rule in watched:
        weight = positions.get(rule["instrument"], Decimal(0))
        above = weight >= rule["threshold"]
        if above and rule["previously_above"] is False:
            query(connection, """
                INSERT INTO product_alerts (id, workspace_id, rule_id, snapshot_date, weight)
                VALUES (:id, :workspace, :rule, :day, :weight)
                ON CONFLICT (rule_id, snapshot_date) DO NOTHING
            """, id=str(uuid4()), workspace=workspace_id, rule=rule["id"], day=day, weight=weight)
        query(connection, """
            UPDATE product_rules SET last_date=:day, previously_above=:above WHERE id=:id AND workspace_id=:workspace
        """, day=day, above=above, id=rule["id"], workspace=workspace_id)


def scenario(report, instrument, change_percent):
    if report["status"] != "complete":
        raise ValueError("This scenario needs a complete review.")
    selected = next((row for row in report["positions"]
                     if row["instrument"] == instrument and not instrument.startswith("CASH:")), None)
    if selected is None:
        raise ValueError("Choose one of the listed holdings in this review.")
    with localcontext() as ctx:
        ctx.prec = 90
        original = Decimal(report["aud_total"])
        change = Decimal(selected["aud_value"]) * change_percent / 100
        return {"instrument": instrument, "aud_change": format(change, "f"),
                "original_aud": format(original, "f"), "scenario_aud": format(original + change, "f")}
