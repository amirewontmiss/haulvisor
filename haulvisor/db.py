"""
haulvisor.db
------------
Lightweight SQLite wrapper for job persistence.
"""

from __future__ import annotations
import sqlite3, pathlib, json, datetime
from typing import Any, Dict, Optional, List

DB_PATH = pathlib.Path("haulvisor_jobs.db")


def _conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init():
    """Create the jobs table if it doesn't exist."""
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                backend TEXT,
                priority INTEGER,
                status TEXT,
                submitted TEXT,
                completed TEXT,
                gate_count INTEGER,
                depth INTEGER,
                qubits INTEGER,
                elapsed_ms INTEGER,
                error TEXT
            )
            """
        )


# call init at import
init()


def insert_job(rec: Dict[str, Any]) -> None:
    with _conn() as con:
        con.execute(
            """
            INSERT INTO jobs (id, backend, priority, status, submitted,
                              gate_count, depth, qubits)
            VALUES (:id, :backend, :priority, 'queued', :submitted,
                    :gate_count, :depth, :qubits)
            """,
            rec,
        )


def update_job(job_id: str, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=:{k}" for k in fields)
    fields["id"] = job_id
    with _conn() as con:
        con.execute(f"UPDATE jobs SET {cols} WHERE id=:id", fields)


def fetch_job(job_id: str) -> Optional[Dict[str, Any]]:
    con = _conn()
    con.row_factory = sqlite3.Row
    cur = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    con = _conn()
    con.row_factory = sqlite3.Row
    cur = con.execute(
        "SELECT id, backend, priority, status, submitted, completed, elapsed_ms "
        "FROM jobs ORDER BY datetime(submitted) DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in cur]

