import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_id      TEXT PRIMARY KEY,
                status      TEXT NOT NULL,
                filename    TEXT NOT NULL,
                output_file TEXT,
                preview     TEXT,
                stats       TEXT,
                error       TEXT,
                created_at  TEXT NOT NULL
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_logs (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id  TEXT NOT NULL REFERENCES jobs(job_id),
                message TEXT NOT NULL
            )
        """
        )


def create_job(db_path: Path, job_id: str, filename: str) -> None:
    query = (
        "INSERT INTO jobs (job_id, status, filename, created_at) "
        "VALUES (?, ?, ?, ?)"
    )
    params = (job_id, "queued", filename, datetime.now(UTC).isoformat())
    with _connect(db_path) as conn:
        conn.execute(query, params)


def update_job(db_path: Path, job_id: str, **fields) -> None:
    if not fields:
        return
    if "stats" in fields:
        fields["stats"] = json.dumps(fields["stats"])
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    query = f"UPDATE jobs SET {set_clause} WHERE job_id = ?"
    params = (*fields.values(), job_id)
    with _connect(db_path) as conn:
        conn.execute(query, params)


def append_log(db_path: Path, job_id: str, message: str) -> None:
    query = "INSERT INTO job_logs (job_id, message) VALUES (?, ?)"
    params = (job_id, message)
    with _connect(db_path) as conn:
        conn.execute(query, params)


def get_job(db_path: Path, job_id: str) -> dict | None:
    job_query = "SELECT * FROM jobs WHERE job_id = ?"
    logs_query = "SELECT message FROM job_logs WHERE job_id = ? ORDER BY id"
    params = (job_id,)

    with _connect(db_path) as conn:
        row = conn.execute(job_query, params).fetchone()
        if row is None:
            return None

        job = dict(row)

        if job.get("stats"):
            job["stats"] = json.loads(job["stats"])

        logs = conn.execute(logs_query, params).fetchall()
        job["log"] = [r["message"] for r in logs]

        return job


def list_jobs(db_path: Path) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT job_id, filename, status FROM jobs ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def purge_old_jobs(db_path: Path, days: int = 1) -> None:
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    with _connect(db_path) as conn:
        old = conn.execute(
            "SELECT job_id FROM jobs WHERE created_at < ?", (cutoff,)
        ).fetchall()
        for row in old:
            conn.execute("DELETE FROM job_logs WHERE job_id = ?", (row["job_id"],))
        conn.execute("DELETE FROM jobs WHERE created_at < ?", (cutoff,))
