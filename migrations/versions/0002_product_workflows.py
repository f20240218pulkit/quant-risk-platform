"""Add leased jobs, evidence dates and persistent product controls."""
from alembic import op

revision = "0002_product_workflows"
down_revision = "0001_workbench"


def upgrade():
    op.execute("ALTER TABLE product_sessions ADD COLUMN authenticated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE product_imports ADD COLUMN holdings_date date")
    op.execute("ALTER TABLE product_imports ADD COLUMN is_refresh boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE product_jobs DROP CONSTRAINT product_jobs_state_check")
    op.execute("ALTER TABLE product_jobs ADD CONSTRAINT product_jobs_state_check CHECK (state IN ('queued','running','complete','failed'))")
    op.execute("ALTER TABLE product_jobs ADD COLUMN lease_token varchar(36), ADD COLUMN lease_until timestamptz")
    op.execute("CREATE INDEX product_expired_jobs ON product_jobs (lease_until) WHERE state='running'")
    op.execute("""
        CREATE TABLE product_rules (
            id varchar(36) PRIMARY KEY,
            workspace_id varchar(36) NOT NULL REFERENCES product_workspaces(id) ON DELETE CASCADE,
            instrument text NOT NULL,
            threshold numeric(7,4) NOT NULL CHECK (threshold > 0 AND threshold <= 100),
            last_date date,
            previously_above boolean,
            UNIQUE (workspace_id, instrument, threshold),
            UNIQUE (workspace_id, id)
        )
    """)
    op.execute("""
        CREATE TABLE product_alerts (
            id varchar(36) PRIMARY KEY,
            workspace_id varchar(36) NOT NULL,
            rule_id varchar(36) NOT NULL,
            snapshot_date date NOT NULL,
            weight numeric(12,8) NOT NULL,
            acknowledged_at timestamptz,
            UNIQUE (rule_id, snapshot_date),
            FOREIGN KEY (workspace_id, rule_id) REFERENCES product_rules(workspace_id, id) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX product_alert_inbox ON product_alerts (workspace_id, snapshot_date DESC)")
    op.execute("""
        CREATE TABLE product_refresh (
            workspace_id varchar(36) PRIMARY KEY REFERENCES product_workspaces(id) ON DELETE CASCADE,
            enabled boolean NOT NULL,
            last_period date
        )
    """)
    op.execute("""
        CREATE TABLE product_identities (
            issuer text NOT NULL,
            subject text NOT NULL,
            workspace_id varchar(36) UNIQUE NOT NULL REFERENCES product_workspaces(id) ON DELETE CASCADE,
            PRIMARY KEY (issuer, subject)
        )
    """)
    for table in ("product_rules", "product_alerts"):
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
                GRANT DELETE ON product_workspaces TO workbench_runtime;
                GRANT UPDATE (lease_token, lease_until) ON product_jobs TO workbench_runtime;
                GRANT SELECT, INSERT, DELETE ON product_rules TO workbench_runtime;
                GRANT UPDATE (last_date, previously_above) ON product_rules TO workbench_runtime;
                GRANT SELECT, INSERT ON product_alerts TO workbench_runtime;
                GRANT UPDATE (acknowledged_at) ON product_alerts TO workbench_runtime;
                GRANT SELECT, INSERT, UPDATE ON product_refresh TO workbench_runtime;
                GRANT SELECT, INSERT ON product_identities TO workbench_runtime;
            END IF;
        END
        $grant$
    """)


def downgrade():
    for table in ("product_identities", "product_refresh", "product_alerts", "product_rules"):
        op.drop_table(table)
    op.execute("DROP INDEX product_expired_jobs")
    op.execute("UPDATE product_jobs SET state = 'queued', attempts = least(attempts, 2) WHERE state = 'running'")
    op.execute("ALTER TABLE product_jobs DROP COLUMN lease_token, DROP COLUMN lease_until")
    op.execute("ALTER TABLE product_jobs DROP CONSTRAINT product_jobs_state_check")
    op.execute("ALTER TABLE product_jobs ADD CONSTRAINT product_jobs_state_check CHECK (state IN ('queued','complete','failed'))")
    op.execute("ALTER TABLE product_imports DROP COLUMN holdings_date, DROP COLUMN is_refresh")
    op.execute("ALTER TABLE product_sessions DROP COLUMN authenticated_at")
