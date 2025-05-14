"""
haulvisor.monitoring.logger
---------------------------
JSON log per job + simple pretty-printer.
"""

from __future__ import annotations
from datetime import datetime
import json, pathlib, time
from typing import Any, Dict

LOG_PATH = pathlib.Path(".haulvisor_logs")
LOG_PATH.mkdir(exist_ok=True)


def _stamp() -> str:
    return datetime.utcnow().isoformat()


# ── public API ──────────────────────────────────────────────────────────── #

def log_submit(job_id: str, backend: str, circ: str, metrics: Dict[str, Any]):
    """Create a new log file at submit-time."""
    (LOG_PATH / f"{job_id}.json").write_text(
        json.dumps(
            {
                "job": job_id,
                "backend": backend,
                "submitted": _stamp(),
                "circ": circ,
                **metrics,
            }
        )
    )


def log_complete(job_id: str):
    """Add completion timestamp + elapsed_ms."""
    path = LOG_PATH / f"{job_id}.json"
    data = json.loads(path.read_text())
    t0 = datetime.fromisoformat(data["submitted"])
    t1 = datetime.utcnow()
    data["completed"] = t1.isoformat()
    data["elapsed_ms"] = int((t1 - t0).total_seconds() * 1000)
    path.write_text(json.dumps(data, indent=2))


def pretty(job_id: str):
    path = LOG_PATH / f"{job_id}.json"
    print(path.read_text())

