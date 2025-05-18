"""
haulvisor.scheduler.job_queue
-----------------------------
Thread-based executor with priority queue, retry support, and SQLite persistence.

Priority levels
---------------
"high"   → 0   (runs first)
"normal" → 1   (default)
"low"    → 2   (runs last)

enqueue(..., priority="high", max_retries=5)
"""

from __future__ import annotations

import threading
import time
import uuid
import traceback # For printing full exception tracebacks
from queue import PriorityQueue, Empty # Thread-safe priority queue
from dataclasses import dataclass, field # For creating data classes
from typing import Union, Any, Type, Optional # For type hinting
from datetime import datetime # For timestamps

# HaulVisor internal module imports
from ..monitoring import logger # For logging job events
from .. import db # For database interactions (get_job_by_id, update_job)

# --------------------------------------------------------------------------- #
# Data model for items stored in the priority queue                           #
# --------------------------------------------------------------------------- #

@dataclass(order=True) # order=True allows items to be sorted by priority in PriorityQueue
class _PQItem:
    """Represents an item in the job priority queue."""
    priority: int # Numerical priority (lower means higher priority)
    enqueue_time: float # Unix timestamp (from time.time()) when the job was enqueued, for tie-breaking
    
    # Fields below are not used for comparison in the priority queue (compare=False)
    job_id: str = field(compare=False) # Unique ID for the job
    device_cls: Type[Any] = field(compare=False) # The device class (e.g., QiskitDevice) to execute the job
    circ: str = field(compare=False) # The QASM circuit string
    max_retries: int = field(compare=False, default=3) # Maximum number of retries for this job
    attempt: int = field(compare=False, default=0) # Current attempt number for this job

# --------------------------------------------------------------------------- #
# Global variables for the job queue and results                              #
# --------------------------------------------------------------------------- #

_pq: PriorityQueue[_PQItem] = PriorityQueue() # The main priority queue for pending jobs
_results: dict[str, Any] = {} # Dictionary to store results (or exceptions) of completed jobs

# Mapping for string priorities to numerical values
_PRIO_MAP = {"high": 0, "normal": 1, "low": 2}

# --------------------------------------------------------------------------- #
# Worker thread function that processes jobs from the queue                   #
# --------------------------------------------------------------------------- #

def _worker():
    """
    Worker function that runs in a separate thread.
    Continuously fetches jobs from the priority queue and executes them.
    """
    while True:
        try:
            # Get a job item from the queue. Blocks for up to 1 second if queue is empty.
            item: _PQItem = _pq.get(timeout=1)
        except Empty:
            # If queue is empty, continue to the next iteration (effectively polling)
            continue

        job_run_result: Any = None # To store the result of device.run()
        submitted_iso_timestamp: str | None = None # To store the job's submission timestamp
        
        # Attempt to fetch job details (especially submitted timestamp) from the database
        try:
            if hasattr(db, 'get_job_by_id'):
                job_db_details = db.get_job_by_id(item.job_id)
                if job_db_details:
                    submitted_iso_timestamp = job_db_details.get("submitted")
            else:
                # This indicates a potential issue if get_job_by_id is expected but not found
                print(f"Worker: db.get_job_by_id function not found. Cannot fetch submitted_iso_timestamp for job {item.job_id}.")
        except Exception as db_exc:
            print(f"Worker: Error fetching job details for {item.job_id} from DB: {db_exc}")
        
        current_utc_time = datetime.utcnow() # Get current time once for potential use in logging

        try:
            # Instantiate the device and execute the circuit
            device = item.device_cls()
            compiled_program = device.compile(item.circ) # Compile QASM to backend-specific format
            job_run_result = device.run(compiled_program) # Run the compiled program
            
            # Optional: Call device-specific monitoring if available
            if hasattr(device, 'monitor') and callable(getattr(device, 'monitor')):
                device.monitor(job_run_result)

            # Job completed successfully: update database and log
            db.update_job(
                job_id=item.job_id, 
                status="completed", 
                completed=current_utc_time.isoformat(), # Log completion time
                result_summary=str(job_run_result)[:200] # Store a summary of the result
            )

            logger.log_complete(
                job_id=item.job_id,
                result=job_run_result,
                submitted_iso_timestamp=submitted_iso_timestamp,
                completion_time=current_utc_time # Pass the datetime object
            )
            _results[item.job_id] = job_run_result # Make result available to waiters

        except Exception as e:
            # An error occurred during job execution
            traceback.print_exc() # Print the full exception traceback for debugging
            item.attempt += 1 # Increment attempt counter

            if item.attempt <= item.max_retries:
                # If retries are left, re-enqueue the job with a backoff delay
                backoff_duration = 2 ** (item.attempt - 1)  # Exponential backoff: 1s, 2s, 4s, ...
                print(f"Job {item.job_id} attempt {item.attempt} failed. Retrying in {backoff_duration}s. Error: {e}")
                time.sleep(backoff_duration)
                _pq.put(item)  # Re-add item to the queue for another attempt
            else: 
                # All retries exhausted, mark job as failed
                print(f"Job {item.job_id} failed after {item.max_retries + 1} attempts (initial + retries). Error: {e}")
                
                # Update database for the failed job
                db.update_job(
                    job_id=item.job_id, 
                    status="failed", 
                    completed=current_utc_time.isoformat(), # Log failure time as 'completed'
                    error_message=str(e) # Ensure this uses 'error_message'
                )
                # Log the error event
                logger.log_error(
                    job_id=item.job_id,
                    error_message=str(e),
                    submitted_iso_timestamp=submitted_iso_timestamp,
                    error_time=current_utc_time # Pass the datetime object
                )
                _results[item.job_id] = e # Store the exception for waiters
        finally:
            # Signal that the fetched task is done, regardless of success or failure
            _pq.task_done()

# Launch the background worker thread when this module is imported
# daemon=True ensures the thread exits when the main program exits
threading.Thread(target=_worker, daemon=True, name="HaulVisorWorker").start()

# --------------------------------------------------------------------------- #
# Public API for enqueuing jobs and waiting for results                       #
# --------------------------------------------------------------------------- #

def enqueue(
    device_cls: Type[Any], 
    circ: str,
    *,
    priority: Union[str, int] = "normal", # Can be string ("high", "normal", "low") or int
    max_retries: int = 3,
) -> str:
    """
    Inserts a job into the priority queue for execution.

    Parameters:
        device_cls: The specific device class (e.g., QiskitDevice) to run the circuit.
        circ: The OpenQASM circuit string.
        priority: Job priority. Can be "high", "normal", "low", or an integer.
                  Lower integer means higher priority.
        max_retries: Number of automatic retries if the job fails.

    Returns:
        str: A unique job ID for the enqueued job.
    """
    prio_val_intermediate = priority
    # Convert string priority to numerical value using _PRIO_MAP
    if isinstance(priority, str):
        prio_val_intermediate = _PRIO_MAP.get(priority.lower(), priority) # Case-insensitive lookup
    
    prio_val: int
    if isinstance(prio_val_intermediate, int):
        prio_val = prio_val_intermediate
    elif isinstance(prio_val_intermediate, str): # If it's still a string (not in map), try to convert
        try:
            prio_val = int(prio_val_intermediate)
        except ValueError:
            # Default to 'normal' priority if conversion fails
            print(f"Warning: Priority '{priority}' not a recognized name or integer. Defaulting to normal ({_PRIO_MAP.get('normal', 1)}).")
            prio_val = _PRIO_MAP.get("normal", 1)
    else: # Should not happen if _PRIO_MAP values are ints and string priorities are handled
        print(f"Warning: Priority '{priority}' has unexpected type. Defaulting to normal ({_PRIO_MAP.get('normal', 1)}).")
        prio_val = _PRIO_MAP.get("normal", 1)

    job_id = str(uuid.uuid4()) # Generate a unique job ID
    
    # Create the job item to be added to the queue
    item = _PQItem(
        priority=prio_val,
        enqueue_time=time.time(), # Current time for tie-breaking in queue
        job_id=job_id,
        device_cls=device_cls,
        circ=circ,
        max_retries=max_retries,
        attempt=0 # Initial attempt
    )
    _pq.put(item) # Add the item to the priority queue
    return job_id

def wait(job_id: str) -> Any: 
    """
    Blocks execution until the specified job_id has a result (or an exception).
    Once the result is retrieved, it's removed from the internal store.

    Parameters:
        job_id: The ID of the job to wait for.

    Returns:
        Any: The result object from the backend, or an Exception if the job ultimately failed.
    """
    while job_id not in _results:
        time.sleep(0.1)  # Polling interval to check for results
    
    # .pop() retrieves and removes the item. 
    # This means wait() is typically effective once per job result.
    return _results.pop(job_id)


