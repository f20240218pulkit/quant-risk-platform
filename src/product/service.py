"""Transactional commands and queries for the synthetic Workbench."""
from contextlib import contextmanager
import json
from hashlib import sha256
from secrets import token_urlsafe
from uuid import uuid4

from sqlalchemy import text

from .database import scope
from .valuation import parse_holdings


def query(connection, sql, **params):
    return connection.execute(text(sql), params)


def get_workspace(connection, token):
    if not token or len(token) > 128:
        return None
    return query(connection, """
        SELECT workspace_id FROM product_sessions
        WHERE token_hash = :digest AND expires_at > now()
    """, digest=sha256(token.encode()).hexdigest()).scalar_one_or_none()


def close_session(connection, token):
    if token and len(token) <= 128:
        query(connection, "DELETE FROM product_sessions WHERE token_hash = :digest",
              digest=sha256(token.encode()).hexdigest())


def open_session(connection):
    workspace_id = str(uuid4())
    token = token_urlsafe(32)
    query(connection, "INSERT INTO product_workspaces (id) VALUES (:id)", id=workspace_id)
    query(connection, """
        INSERT INTO product_sessions (token_hash, workspace_id, expires_at)
        VALUES (:digest, :workspace, now() + interval '8 hours')
    """, digest=sha256(token.encode()).hexdigest(), workspace=workspace_id)
    return workspace_id, token


def store_import(connection, workspace_id, snapshot_date, data):
    positions, issues = parse_holdings(data)
    digest = sha256(data).hexdigest()
    result = query(connection, """
        INSERT INTO product_imports (id, workspace_id, snapshot_date, input_hash, positions, issues)
        VALUES (:id, :workspace, :snapshot_date, :digest, CAST(:positions AS jsonb), CAST(:issues AS jsonb))
        ON CONFLICT (workspace_id, snapshot_date, input_hash) DO NOTHING
        RETURNING id
    """, id=str(uuid4()), workspace=workspace_id, snapshot_date=snapshot_date,
        digest=digest, positions=json.dumps(positions), issues=json.dumps(issues))
    import_id = result.scalar_one_or_none()
    if import_id is None:
        import_id = query(connection, """
            SELECT id FROM product_imports WHERE workspace_id = :workspace
                AND snapshot_date = :snapshot_date AND input_hash = :digest
        """, workspace=workspace_id, snapshot_date=snapshot_date,
            digest=digest).scalar_one()
    return dict(query(connection, """
        SELECT id, snapshot_date, positions, issues, confirmed_at FROM product_imports
        WHERE workspace_id = :workspace AND id = :id
    """, workspace=workspace_id, id=import_id).mappings().one())


def confirm_import(connection, workspace_id, import_id):
    draft = query(connection, """
        SELECT issues FROM product_imports WHERE workspace_id = :workspace AND id = :id FOR UPDATE
    """, workspace=workspace_id, id=import_id).mappings().one_or_none()
    if draft is None:
        return None
    if draft["issues"]:
        return {"issues": draft["issues"]}
    query(connection, """
        UPDATE product_imports SET confirmed_at = COALESCE(confirmed_at, now())
        WHERE workspace_id = :workspace AND id = :id
    """, workspace=workspace_id, id=import_id)
    query(connection, """
        INSERT INTO product_jobs (id, workspace_id, import_id)
        VALUES (:id, :workspace, :import_id) ON CONFLICT (import_id) DO NOTHING
    """, id=str(uuid4()), workspace=workspace_id, import_id=import_id)
    return dict(query(connection, """
        SELECT id, state FROM product_jobs WHERE workspace_id = :workspace AND import_id = :id
    """, workspace=workspace_id, id=import_id).mappings().one())


def owned_report(connection, workspace_id, report_id):
    row = query(connection, """
        SELECT id, evidence, published_at FROM product_reports WHERE workspace_id = :workspace AND id = :id
    """, workspace=workspace_id, id=report_id).mappings().one_or_none()
    if row is None:
        return None
    return {"id": row["id"], "published_at": row["published_at"], **row["evidence"]}


@contextmanager
def scoped_connection(engine, token):
    """Open an explicitly scoped transaction for a browser request."""
    # A context manager keeps membership and the transaction-local RLS setting
    # together and clears the scope when the pooled connection is returned.
    with engine.begin() as connection:
        workspace_id = get_workspace(connection, token)
        if workspace_id:
            scope(connection, workspace_id)
        yield connection, workspace_id
