"""
haulvisor.monitoring.logger
---------------------------
JSON log per job + simple pretty-printer.
"""

from __future__ import annotations
from datetime import datetime
import json
import pathlib # Corrected import
from typing import Any, Dict, Optional # Added Optional

LOG_PATH = pathlib.Path(".haulvisor_logs")
LOG_PATH.mkdir(exist_ok=True)


def _stamp() -> str:
    return datetime.utcnow().isoformat()


# ── public API ──────────────────────────────────────────────────────────── #

def log_submit(
    job_id: str, 
    backend: str, 
    circ: str, 
    metrics: Dict[str, Any], 
    model_name: Optional[str] = None # Added optional model_name
):
    """Create a new log file at submit-time."""
    log_data = {
        "job": job_id,
        "backend": backend,
        "submitted": _stamp(),
        "model_name": model_name if model_name else "N/A", # Include model_name
        "circ": circ,
        **metrics, # Unpack metrics dictionary into the log
        "status": "submitted" # Initial status
    }
    log_file_path = LOG_PATH / f"{job_id}.json"
    try:
        log_file_path.write_text(json.dumps(log_data, indent=2))
    except Exception as e:
        print(f"Error writing submit log for job {job_id}: {e}")


def log_complete(
    job_id: str, 
    result: Any, # Added result
    submitted_iso_timestamp: Optional[str], # Added submitted_timestamp
    completion_time: Optional[datetime] = None # Added completion_time
):
    """Add completion timestamp, elapsed_ms, and result to the log."""
    path = LOG_PATH / f"{job_id}.json"
    if not path.exists():
        print(f"Warning: Log file for job {job_id} not found for completion update.")
        # Optionally create a basic log entry if it's missing
        error_log_data = {
            "job": job_id,
            "error": "Submit log missing, completion recorded.",
            "status": "completed_with_missing_submit_log",
            "completed": (completion_time or datetime.utcnow()).isoformat(),
            "result_summary": str(result)[:200] # Store a summary of the result
        }
        path.write_text(json.dumps(error_log_data, indent=2))
        return

    try:
        data = json.loads(path.read_text())
        
        t1 = completion_time or datetime.utcnow() # Use provided or current time
        data["completed"] = t1.isoformat()
        data["status"] = "completed"
        data["result_summary"] = str(result)[:200] # Store a summary, avoid overly large logs

        if submitted_iso_timestamp:
            try:
                t0 = datetime.fromisoformat(submitted_iso_timestamp)
                data["elapsed_ms"] = int((t1 - t0).total_seconds() * 1000)
            except ValueError:
                data["elapsed_ms"] = "Error calculating (invalid submitted timestamp)"
        else: # Fallback if submitted_timestamp wasn't available
             data["elapsed_ms"] = "N/A (submitted timestamp missing)"

        path.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error writing complete log for job {job_id}: {e}")

def log_error(
    job_id: str, 
    error_message: str, 
    submitted_iso_timestamp: Optional[str], 
    error_time: Optional[datetime] = None # Added error_time
):
    """Log an error for a job."""
    path = LOG_PATH / f"{job_id}.json"
    t_error = error_time or datetime.utcnow()

    if not path.exists():
        print(f"Warning: Log file for job {job_id} not found for error update.")
        # Create a new log entry for the error if submit log was missing
        error_log_data = {
            "job": job_id,
            "error_time": t_error.isoformat(),
            "status": "failed",
            "error_message": error_message,
        }
        if submitted_iso_timestamp:
             error_log_data["submitted_approx"] = submitted_iso_timestamp # Indicate it might be from DB
        path.write_text(json.dumps(error_log_data, indent=2))
        return
        
    try:
        data = json.loads(path.read_text())
        data["error_time"] = t_error.isoformat()
        data["status"] = "failed"
        data["error_message"] = error_message

        if submitted_iso_timestamp:
            try:
                t0 = datetime.fromisoformat(submitted_iso_timestamp)
                data["elapsed_ms_until_error"] = int((t_error - t0).total_seconds() * 1000)
            except ValueError:
                data["elapsed_ms_until_error"] = "Error calculating (invalid submitted timestamp)"
        else:
            data["elapsed_ms_until_error"] = "N/A (submitted timestamp missing)"
            
        path.write_text(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error writing error log for job {job_id}: {e}")


def pretty(job_id: str):
    """Pretty-prints the JSON log for a given job ID."""
    path = LOG_PATH / f"{job_id}.json"
    if path.exists():
        try:
            # Load and re-dump with indent for consistent pretty printing
            data = json.loads(path.read_text())
            print(json.dumps(data, indent=2))
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from log file: {path}")
            print("\n--- Raw Log Content ---")
            print(path.read_text())
        except Exception as e:
            print(f"Error reading or printing log for job {job_id}: {e}")
    else:
        print(f"Log file not found for job ID: {job_id}")


