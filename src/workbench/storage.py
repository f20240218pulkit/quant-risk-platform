"""SQLite persistence for one instance, with owner-scoped reads and writes."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

SCHEMA = """
create table if not exists reviews (
    owner text not null, id text not null, name text not null,
    created_at text not null, payload text not null, primary key(owner, id)
);
create table if not exists rules (
    owner text not null, id text not null, name text not null,
    kind text not null, threshold real not null, primary key(owner, id)
);
create table if not exists alerts (
    owner text not null, id text not null, rule_id text not null,
    review_id text not null, as_of text not null, message text not null,
    acknowledged int not null default 0, primary key(owner, id),
    unique(owner, rule_id, review_id)
);
create table if not exists jobs (
    owner text not null, id text not null, kind text not null, payload text not null,
    status text not null default 'queued', created real not null, available real not null,
    lease real, claim text, attempts int not null default 0, result text,
    primary key(owner, id)
);
create index if not exists jobs_ready on jobs(status, available, lease);
"""


def identity_key(issuer, subject, expiration, now=None):
    if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
        raise ValueError("Identity is missing its issuer or subject.")
    if not isinstance(expiration, int) or expiration <= (time.time() if now is None else now):
        raise ValueError("Your session has expired. Sign in again.")
    return hashlib.sha256(json.dumps([issuer, subject], ensure_ascii=True).encode()).hexdigest()


def _json(payload):
    return json.dumps(payload, separators=(",", ":"), allow_nan=False)


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.touch(mode=0o600, exist_ok=True)
        with self.connection() as db:
            db.execute("pragma journal_mode = wal")
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save_review(self, owner, name, report):
        name = name.strip()
        if not 1 <= len(name) <= 80:
            raise ValueError("Enter a name from 1 to 80 characters.")
        key = report["valuation_id"]
        now = datetime.now(timezone.utc).isoformat()
        with self.connection() as db:
            db.execute("insert or ignore into reviews values(?,?,?,?,?)", (owner, key, name, now, _json(report)))
            if report["source"] == "synthetic demo":
                return key
            for rule in db.execute("select * from rules where owner=? and name=?", (owner, name)).fetchall():
                if rule["kind"] == "largest":
                    observed = max(float(p["weight"]) for p in report["valuation"]["positions"])
                    text = "Largest holding weight"
                else:
                    observed = report["risk"]["historical_var"]["var_pct"]
                    text = "One-session historical VaR"
                if observed >= rule["threshold"]:
                    alert_id = hashlib.sha256(f"{rule['id']}:{key}".encode()).hexdigest()
                    db.execute("""insert or ignore into alerts(owner,id,rule_id,review_id,as_of,message)
                                  values(?,?,?,?,?,?)""",
                               (owner, alert_id, rule["id"], key, report["session_end"],
                                f"{text} was {observed:.2%} against your {rule['threshold']:.2%} threshold."))
        return key

    def reviews(self, owner):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "select id,name,created_at from reviews where owner=? order by created_at desc limit 100", (owner,))]

    def read_review(self, owner, key):
        with self.connection() as db:
            row = db.execute("select payload from reviews where owner=? and id=?", (owner, key)).fetchone()
            return json.loads(row[0]) if row else None

    def delete_review(self, owner, key):
        with self.connection() as db:
            db.execute("delete from alerts where owner=? and review_id=?", (owner, key))
            return db.execute("delete from reviews where owner=? and id=?", (owner, key)).rowcount == 1

    def add_rule(self, owner, name, kind, threshold):
        if kind not in {"largest", "var"} or not 0 < threshold <= 1 or not 1 <= len(name.strip()) <= 80:
            raise ValueError("Supply a portfolio name and a threshold greater than zero up to 100%.")
        key = hashlib.sha256(_json([name.strip(), kind, threshold]).encode()).hexdigest()
        with self.connection() as db:
            db.execute("insert or ignore into rules values(?,?,?,?,?)", (owner, key, name.strip(), kind, threshold))

    def rules(self, owner):
        with self.connection() as db:
            return [dict(row) for row in db.execute("select * from rules where owner=? order by name", (owner,))]

    def delete_rule(self, owner, key):
        with self.connection() as db:
            db.execute("delete from rules where owner=? and id=?", (owner, key))

    def alerts(self, owner):
        with self.connection() as db:
            return [dict(row) for row in db.execute(
                "select * from alerts where owner=? order by as_of desc limit 100", (owner,))]

    def acknowledge(self, owner, key):
        with self.connection() as db:
            db.execute("update alerts set acknowledged=1 where owner=? and id=?", (owner, key))

    def purge(self, owner):
        with self.connection() as db:
            for table in ("alerts", "rules", "reviews", "jobs"):
                db.execute(f"delete from {table} where owner=?", (owner,))

    def enqueue(self, owner, kind, payload, now=None):
        if kind not in {"research", "refresh"}:
            raise ValueError("Unsupported job type.")
        now = time.time() if now is None else now
        encoded = _json(payload)
        if len(encoded) > 16_000_000:
            raise ValueError("Job input is too large.")
        key = hashlib.sha256(_json([kind, payload]).encode()).hexdigest()
        with self.connection() as db:
            db.execute("begin immediate")
            row = db.execute("select status from jobs where owner=? and id=?", (owner, key)).fetchone()
            if row and row["status"] != "failed":
                return key
            queued = db.execute("select count(*) from jobs where owner=? and status in ('queued','running')",
                                (owner,)).fetchone()[0]
            if queued >= 3:
                raise ValueError("Wait for one of your three queued or running jobs to finish.")
            db.execute("""insert into jobs(owner,id,kind,payload,created,available) values(?,?,?,?,?,?)
                          on conflict(owner,id) do update set status='queued',payload=excluded.payload,
                          created=excluded.created,available=excluded.available,attempts=0,result=null,
                          claim=null,lease=null""", (owner,key,kind,encoded,now,now))
        return key

    def claim(self, now=None, lease_seconds=600):
        now = time.time() if now is None else now
        claim = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("begin immediate")
            db.execute("""update jobs set status='failed', result='{"error":"Worker lease expired."}', payload='{}'
                          where status='running' and lease<=? and attempts>=3""", (now,))
            row = db.execute("""select * from jobs where attempts<3 and
                                ((status='queued' and available<=?) or (status='running' and lease<=?))
                                order by created limit 1""", (now, now)).fetchone()
            if row is None:
                return None
            db.execute("""update jobs set status='running',lease=?,claim=?,attempts=attempts+1
                          where owner=? and id=?""", (now+lease_seconds, claim, row["owner"], row["id"]))
            return {**dict(row), "payload": json.loads(row["payload"]),
                    "claim": claim, "attempts": row["attempts"] + 1}

    def finish(self, job, result, *, error=False, retry=False, now=None):
        now = time.time() if now is None else now
        with self.connection() as db:
            db.execute("begin immediate")
            # Stale workers cannot publish after another attempt has claimed the job.
            row = db.execute("""select 1 from jobs where owner=? and id=? and claim=? and
                                 status='running' and lease>?""",
                             (job["owner"], job["id"], job["claim"], now)).fetchone()
            if not row:
                return False
            retry = retry and job["attempts"] < 3
            status = "queued" if retry else ("failed" if error else "complete")
            db.execute("""update jobs set status=?,result=?,available=?,lease=null,claim=null,
                          payload=case when ? then payload else '{}' end
                          where owner=? and id=? and claim=?""",
                       (status, _json(result), now+30, retry, job["owner"], job["id"], job["claim"]))
            return True

    def jobs(self, owner):
        with self.connection() as db:
            return [dict(row) for row in db.execute("""select id,kind,status,attempts from jobs where owner=?
                                                        order by created desc limit 25""", (owner,))]

    def job_result(self, owner, key):
        with self.connection() as db:
            row = db.execute("select result from jobs where owner=? and id=?", (owner, key)).fetchone()
            return json.loads(row[0]) if row and row[0] else None
