"""Create separate Workbench product state."""
from alembic import op

revision = "0001_workbench"
down_revision = None


def upgrade():
    op.execute("""
        CREATE TABLE product_workspaces (
            id varchar(36) PRIMARY KEY,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE product_sessions (
            token_hash char(64) PRIMARY KEY,
            workspace_id varchar(36) NOT NULL REFERENCES product_workspaces(id) ON DELETE CASCADE,
            expires_at timestamptz NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE product_imports (
            id varchar(36) PRIMARY KEY,
            workspace_id varchar(36) NOT NULL REFERENCES product_workspaces(id) ON DELETE CASCADE,
            snapshot_date date NOT NULL,
            input_hash char(64) NOT NULL,
            positions jsonb NOT NULL CHECK (jsonb_typeof(positions) = 'array'),
            issues jsonb NOT NULL CHECK (jsonb_typeof(issues) = 'array'),
            created_at timestamptz NOT NULL DEFAULT now(),
            confirmed_at timestamptz,
            UNIQUE (workspace_id, id),
            UNIQUE (workspace_id, snapshot_date, input_hash)
        )
    """)
    # The dispatcher sees only queue metadata and identifiers. Holdings and
    # reports are separately protected by workspace policies.
    op.execute("""
        CREATE TABLE product_jobs (
            id varchar(36) PRIMARY KEY,
            workspace_id varchar(36) NOT NULL,
            import_id varchar(36) NOT NULL UNIQUE,
            state text NOT NULL DEFAULT 'queued' CHECK (state IN ('queued', 'complete', 'failed')),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
            available_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (workspace_id, import_id)
                REFERENCES product_imports(workspace_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX product_ready_jobs ON product_jobs (available_at, id) WHERE state = 'queued'")
    op.execute("""
        CREATE TABLE product_reports (
            id varchar(36) PRIMARY KEY,
            workspace_id varchar(36) NOT NULL,
            import_id varchar(36) NOT NULL UNIQUE,
            snapshot_date date NOT NULL,
            evidence jsonb NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
            published_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (workspace_id, import_id)
                REFERENCES product_imports(workspace_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX product_report_history ON product_reports (workspace_id, snapshot_date DESC, published_at DESC)")
    for table in ("product_imports", "product_reports"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY workspace_scope ON {table}
            USING (workspace_id = current_setting('workbench.workspace_id', true))
            WITH CHECK (workspace_id = current_setting('workbench.workspace_id', true))
        """)
    op.execute("""
        DO $grant$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'workbench_runtime') THEN
                GRANT SELECT, INSERT ON product_workspaces TO workbench_runtime;
                GRANT SELECT, INSERT, DELETE ON product_sessions TO workbench_runtime;
                GRANT SELECT, INSERT ON product_imports TO workbench_runtime;
                GRANT UPDATE (confirmed_at) ON product_imports TO workbench_runtime;
                GRANT SELECT, INSERT ON product_jobs TO workbench_runtime;
                GRANT UPDATE (state, attempts, available_at) ON product_jobs TO workbench_runtime;
                GRANT SELECT, INSERT ON product_reports TO workbench_runtime;
            END IF;
        END
        $grant$
    """)


def downgrade():
    for table in ("product_reports", "product_jobs", "product_imports", "product_sessions", "product_workspaces"):
        op.drop_table(table)
