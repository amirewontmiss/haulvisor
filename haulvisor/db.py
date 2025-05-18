"""
haulvisor.db
------------
Lightweight SQLite wrapper for job persistence.
"""

from __future__ import annotations
import sqlite3
import pathlib
# import json # Not used directly in this version
# import datetime # Not used directly in this version
from typing import Any, Dict, Optional, List

DB_PATH = pathlib.Path("haulvisor_jobs.db")


def _conn() -> sqlite3.Connection: # Added type hint for return
    # Using check_same_thread=False is generally for when multiple threads might access
    # the same connection. If each thread/function call gets its own connection via _conn(),
    # it might not be strictly necessary, but it's often used with SQLite in threaded apps.
    # Consider using a single, thread-local connection or a connection pool for more complex scenarios.
    return sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10) # Added timeout


def init():
    """Create the jobs table if it doesn't exist with all necessary columns."""
    with _conn() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                backend TEXT,
                priority INTEGER,
                status TEXT,          -- e.g., 'queued', 'running', 'completed', 'failed'
                submitted TEXT,       -- ISO timestamp
                completed TEXT,       -- ISO timestamp of completion or failure
                gate_count INTEGER,
                depth INTEGER,
                qubits INTEGER,
                elapsed_ms INTEGER,   -- This column exists but isn't explicitly set by current db functions
                error_message TEXT,   -- For storing error messages if a job fails
                result_summary TEXT,  -- For storing a brief summary of the result
                model_path TEXT       -- For storing the path/name of the input model
            )
            """
        )
        # You might want to add indexes for frequently queried columns, e.g., status, submitted
        # con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs (status);")
        # con.execute("CREATE INDEX IF NOT EXISTS idx_jobs_submitted ON jobs (submitted);")
    print(f"Database initialized at {DB_PATH.resolve()}")


# Call init at import to ensure table exists when module is loaded.
init()


def insert_job(rec: Dict[str, Any]) -> None:
    """
    Inserts a new job record into the database.
    Expects 'status' to be set by the caller or defaults to 'queued'.
    """
    # Ensure all required fields for the INSERT are present in rec or have defaults
    # 'status' is explicitly set to 'queued' in the SQL.
    # 'model_path' is now expected from rec.
    with _conn() as con:
        con.execute(
            """
            INSERT INTO jobs (id, backend, priority, status, submitted,
                              gate_count, depth, qubits, model_path)
            VALUES (:id, :backend, :priority, 'queued', :submitted,
                    :gate_count, :depth, :qubits, :model_path)
            """,
            rec,
        )

def update_job(job_id: str, **fields: Any) -> None:
    """
    Updates specified fields for a given job_id.
    Example: update_job(job_id, status="completed", completed="timestamp", result_summary="...")
    """
    if not fields:
        return # No fields to update
    
    # Filter out None values to avoid setting columns to NULL unintentionally unless explicitly passed
    # However, the current implementation will include keys with None values, setting them to NULL.
    # If that's not desired, filter fields:
    # valid_fields = {k: v for k, v in fields.items() if v is not None}
    # if not valid_fields: return
    # cols = ", ".join(f"{k}=:{k}" for k in valid_fields)
    # valid_fields["id"] = job_id
    # query = f"UPDATE jobs SET {cols} WHERE id=:id"
    # con.execute(query, valid_fields)

    cols = ", ".join(f"{k}=:{k}" for k in fields)
    fields["id"] = job_id # Add job_id to the dictionary for the query
    
    query = f"UPDATE jobs SET {cols} WHERE id=:id"
    
    with _conn() as con:
        try:
            con.execute(query, fields)
        except sqlite3.Error as e:
            print(f"Error updating job {job_id} with fields {fields}: {e}")
            # Potentially re-raise or handle more gracefully


def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]: # Renamed from fetch_job
    """Fetches a single job by its ID."""
    with _conn() as con:
        con.row_factory = sqlite3.Row # Makes rows accessible by column name
        cur = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """Lists recent jobs, ordered by submission time."""
    with _conn() as con:
        con.row_factory = sqlite3.Row
        # Selecting more columns that are now available
        cur = con.execute(
            """
            SELECT id, backend, priority, status, submitted, completed, 
                   elapsed_ms, model_path, error_message, result_summary
            FROM jobs ORDER BY datetime(submitted) DESC LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()] # Use fetchall()


