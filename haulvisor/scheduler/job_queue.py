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
import traceback
from queue import PriorityQueue, Empty
from dataclasses import dataclass, field
from typing import Union

from ..monitoring import logger
from .. import db

# --------------------------------------------------------------------------- #
# Data model                                                                  #
# --------------------------------------------------------------------------- #

@dataclass(order=True)
class _PQItem:
    priority: int
    enqueue_time: float
    job_id: str = field(compare=False)
    device_cls: type = field(compare=False)
    circ: str = field(compare=False)
    max_retries: int = field(compare=False, default=3)
    attempt: int = field(compare=False, default=0)

# --------------------------------------------------------------------------- #
# Globals                                                                     #
# --------------------------------------------------------------------------- #

_pq: PriorityQueue[_PQItem] = PriorityQueue()
_results: dict[str, object] = {}

_PRIO_MAP = {"high": 0, "normal": 1, "low": 2}

# --------------------------------------------------------------------------- #
# Worker                                                                      #
# --------------------------------------------------------------------------- #

def _worker():
    while True:
        try:
            item: _PQItem = _pq.get(timeout=1)
        except Empty:
            continue

        try:
            device = item.device_cls()
            compiled = device.compile(item.circ)
            res = device.run(compiled)
            device.monitor(res)

            # mark done in DB & JSON log first
            db.update_job(item.job_id, status="done")
            logger.log_complete(item.job_id)

            # then store result to release waiters
            _results[item.job_id] = res

        except Exception as e:
            item.attempt += 1
            if item.attempt <= item.max_retries:
                backoff = 2 ** (item.attempt - 1)  # 1s, 2s, 4s, ...
                time.sleep(backoff)
                _pq.put(item)  # retry
            else:
                # record failure after final retry
                db.update_job(
                    item.job_id,
                    status="error",
                    error=str(e),
                )
                logger.log_complete(item.job_id)
                _results[item.job_id] = e
                traceback.print_exc()

        finally:
            _pq.task_done()

# Launch the background worker thread
threading.Thread(target=_worker, daemon=True).start()

# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #

def enqueue(
    device_cls: type,
    circ: str,
    *,
    priority: Union[str, int] = "normal",
    max_retries: int = 3,
) -> str:
    """
    Insert a job into the priority queue.

    Parameters
    ----------
    device_cls : HaulDevice subclass
    circ : str
        The OpenQASM circuit description.
    priority : "high" | "normal" | "low" | int
        Lower number = higher priority.
    max_retries : int
        Number of automatic retries on error.
    """
    prio_val = _PRIO_MAP.get(priority, priority)  # allow numeric override
    job_id = str(uuid.uuid4())
    _pq.put(
        _PQItem(
            priority=prio_val,
            enqueue_time=time.time(),
            job_id=job_id,
            device_cls=device_cls,
            circ=circ,
            max_retries=max_retries,
        )
    )
    return job_id

def wait(job_id: str):
    """
    Block until the given job_id has a result (or exception).

    Returns
    -------
    The backend result object, or an Exception if the job ultimately failed.
    """
    while job_id not in _results:
        time.sleep(0.1)
    return _results.pop(job_id)

