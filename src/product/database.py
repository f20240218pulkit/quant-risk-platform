"""Database connections and transaction-local workspace context."""
import os

from sqlalchemy import create_engine, text


def database_engine(url: str | None = None):
    url = url or os.environ.get("WORKBENCH_DATABASE_URL")
    if not url or not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("Set WORKBENCH_DATABASE_URL to a postgresql+psycopg connection URL.")
    return create_engine(url, pool_pre_ping=True)


def scope(connection, workspace_id: str):
    connection.execute(text("SELECT set_config('workbench.workspace_id', :workspace, true)"),
                       {"workspace": workspace_id})
