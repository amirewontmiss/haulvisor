"""
haulvisor.api.core
------------------
Public façade for compile/dispatch/run/logs with smart path resolution,
backend‐aware QASM, metrics capture, priority/retries, and SQLite persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union
import importlib.resources as pkg_res
from datetime import datetime

from ..compiler import parser, optimizer, qasm_gen
from ..monitoring import logger, metrics
from ..scheduler import job_queue, qpu_router
from ..scheduler.job_queue import _PRIO_MAP
from .. import db


def _resolve_path(path_like: str | Path) -> Path:
    p = Path(path_like)

    if p.is_absolute():
        if p.exists():
            return p
        else:
            raise FileNotFoundError(f"Absolute model file path not found: {p}")

    # Candidates:
    # 1. Relative to the current working directory (where the user ran the command)
    candidate_cwd = Path.cwd() / p
    if candidate_cwd.exists():
        return candidate_cwd.resolve()

    # 2. Relative to the Haulvisor package root
    #    This helps if the user provides a path like "examples/file.json"
    #    and expects it to be found within the package structure,
    #    regardless of where they run the command from.
    candidate_package_root = _HAULVISOR_PACKAGE_ROOT / p
    if candidate_package_root.exists():
        return candidate_package_root.resolve()

    # 3. If the path_like was something like "haulvisor/examples/file.json"
    #    and CWD is ~, this attempts to make it work.
    #    This is implicitly covered if candidate_cwd works when the path includes the top-level dir.
    #    Or if the user is already in the project root.

    raise FileNotFoundError(
        f"Model file not found: {path_like}. "
        f"Tried relative to CWD ({Path.cwd()}) and package root ({_HAULVISOR_PACKAGE_ROOT})."
    )


def _qasm_version_for_backend(backend: str) -> int:
    """Use QASM 2 for PennyLane/Qiskit, QASM 3 otherwise."""
    return 2 if backend.lower() in {"pennylane", "qiskit", "braket", "ibm"} else 3


def compile(
    model_path: Union[str, Path],
    *,
    qasm_version: int = 3,
) -> str:
    """
    Parse → optimise → emit OpenQASM as a string.
    """
    path = _resolve_path(model_path)
    ir_opt = optimizer.optimize(parser.parse(path))
    return qasm_gen.emit(ir_opt, qasm_version=qasm_version)


def dispatch(
    model_path: Union[str, Path],
    backend: str,
    *,
    priority: str = "normal",
    max_retries: int = 3,
) -> str:
    """
    Compile a model, enqueue it on the scheduler, record metrics + DB, and return the job ID.

    Parameters
    ----------
    priority : "high" | "normal" | "low" | int
        Lower number = higher priority.
    max_retries : int
        Number of automatic retries on backend error.
    """
    # 1) Resolve & parse
    path = _resolve_path(model_path)
    ir_opt = optimizer.optimize(parser.parse(path))

    # 2) Calculate metrics
    metrics_dict = metrics.calculate(ir_opt)

    # 3) Emit QASM
    qasm_v = _qasm_version_for_backend(backend)
    circ_qasm = qasm_gen.emit(ir_opt, qasm_version=qasm_v)

    # 4) Enqueue
    device_cls = qpu_router.select(backend)
    prio_val = _PRIO_MAP.get(priority, priority)
    job_id = job_queue.enqueue(
        device_cls, circ_qasm, priority=prio_val, max_retries=max_retries
    )

    # 5) Persist to SQLite
    submitted_ts = datetime.utcnow().isoformat()
    db.insert_job(
        {
            "id": job_id,
            "backend": backend,
            "priority": prio_val,
            "submitted": submitted_ts,
            "gate_count": metrics_dict["gate_count"],
            "depth": metrics_dict["circuit_depth"],
            "qubits": metrics_dict["qubits"],
        }
    )

    # 6) JSON‐log
    logger.log_submit(job_id, backend, circ_qasm, metrics_dict)

    return job_id


def run(
    model_path: Union[str, Path],
    backend: str = "pennylane",
    *,
    priority: str = "normal",
    max_retries: int = 3,
    monitor: bool = True,
) -> Any:
    """
    One-shot: dispatch → wait → (optionally) print logs → return backend result.
    """
    job_id = dispatch(
        model_path,
        backend,
        priority=priority,
        max_retries=max_retries,
    )
    result = job_queue.wait(job_id)
    if monitor:
        logs(job_id)
    return result


def logs(job_id: str) -> None:
    """Pretty‐print the stored JSON log for a given job ID."""
    logger.pretty(job_id)

