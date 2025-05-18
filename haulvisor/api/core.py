"""
haulvisor.api.core
------------------
Public façade for compile/dispatch/run/logs with smart path resolution,
backend‐aware QASM, metrics capture, priority/retries, and SQLite persistence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union, Dict, List, Optional
import importlib.resources as pkg_res 
from datetime import datetime

# HaulVisor internal module imports
from ..compiler import parser, optimizer, qasm_gen
from ..monitoring import logger, metrics
from ..scheduler import job_queue, qpu_router
from ..scheduler.job_queue import _PRIO_MAP 
from .. import db 

_HAULVISOR_PACKAGE_ROOT: Optional[Path] = None
_HAULVISOR_PROJECT_ROOT: Optional[Path] = None

try:
    _HAULVISOR_PACKAGE_ROOT = Path(pkg_res.files("haulvisor")) # type: ignore
    _HAULVISOR_PROJECT_ROOT = _HAULVISOR_PACKAGE_ROOT.parent
except Exception:
    current_file_path = Path(__file__).resolve() 
    _HAULVISOR_PACKAGE_ROOT = current_file_path.parent.parent 
    _HAULVISOR_PROJECT_ROOT = _HAULVISOR_PACKAGE_ROOT.parent


def _resolve_path(path_like: str | Path) -> Path:
    """
    Resolves a string or Path object to an absolute file Path.
    Searches in CWD, then project root, then package root.
    """
    p = Path(path_like)

    if p.is_absolute():
        if p.exists():
            return p.resolve() 
        else:
            raise FileNotFoundError(f"Absolute model file path not found: {p}")

    candidate_cwd = Path.cwd() / p
    if candidate_cwd.exists():
        return candidate_cwd.resolve()

    if _HAULVISOR_PROJECT_ROOT:
        candidate_project_root = _HAULVISOR_PROJECT_ROOT / p
        if candidate_project_root.exists():
            return candidate_project_root.resolve()
    
    if _HAULVISOR_PACKAGE_ROOT:
        candidate_package_internal = _HAULVISOR_PACKAGE_ROOT / p
        if candidate_package_internal.exists():
            return candidate_package_internal.resolve()

    tried_paths_list = [f"CWD ({Path.cwd()})"]
    if _HAULVISOR_PROJECT_ROOT: tried_paths_list.append(f"Project Root ({_HAULVISOR_PROJECT_ROOT})")
    if _HAULVISOR_PACKAGE_ROOT: tried_paths_list.append(f"Package Root ({_HAULVISOR_PACKAGE_ROOT})")
    
    raise FileNotFoundError(
        f"Model file not found: {path_like}. "
        f"Tried relative to: {', '.join(tried_paths_list)}."
    )


def _qasm_version_for_backend(backend: str) -> int:
    """
    Determines the OpenQASM version to use for a given backend.
    """
    backend_lower = backend.lower()
    qasm2_backends = {"pennylane", "qiskit", "braket", "ibm", "aws-braket"}
    return 2 if backend_lower in qasm2_backends else 3


def compile(
    model_path: Union[str, Path],
    *,
    qasm_version: Optional[int] = None, 
    backend_hint: Optional[str] = None 
) -> str:
    """
    Parses a circuit model, optimizes it, and emits an OpenQASM string.
    """
    path = _resolve_path(model_path)
    ir = parser.parse(path) 
    # --- DEBUG PRINT for compile ---
    print(f"[api/core.py COMPILE DEBUG] Parsed IR. Qubit count: {ir.qubits}")
    ir_opt = optimizer.optimize(ir) 
    print(f"[api/core.py COMPILE DEBUG] Optimized IR. Qubit count: {ir_opt.qubits}")
    # --- END DEBUG PRINT for compile ---
    
    effective_qasm_version = qasm_version
    if effective_qasm_version is None:
        effective_qasm_version = _qasm_version_for_backend(backend_hint if backend_hint else "default")
    
    return qasm_gen.emit(ir_opt, qasm_version=effective_qasm_version, backend_hint=backend_hint)


def dispatch(
    model_path: Path, 
    backend: str,
    *,
    priority: str = "normal",
    max_retries: int = 3,
) -> str:
    """
    Compiles a model, enqueues it on the scheduler, records metrics and DB entry,
    and returns the job ID.
    """
    ir = parser.parse(model_path) 
    print(f"[api/core.py DISPATCH DEBUG] Parsed IR. Qubit count from CircuitIR object: {ir.qubits}") # Original Debug

    ir_opt = optimizer.optimize(ir) 
    # --- NEW DEBUG PRINT ---
    print(f"[api/core.py DISPATCH DEBUG] After optimizer.optimize. Qubit count from ir_opt: {ir_opt.qubits}")
    # --- END NEW DEBUG PRINT ---

    metrics_dict = metrics.calculate(ir_opt) 
    # --- NEW DEBUG PRINT ---
    print(f"[api/core.py DISPATCH DEBUG] After metrics.calculate. Qubit count from metrics_dict: {metrics_dict.get('qubits')}")
    print(f"[api/core.py DISPATCH DEBUG] Qubit count from ir_opt before QASM gen: {ir_opt.qubits}")
    # --- END NEW DEBUG PRINT ---
    
    qasm_v = _qasm_version_for_backend(backend) 
    circ_qasm = qasm_gen.emit(ir_opt, qasm_version=qasm_v, backend_hint=backend) 

    device_cls = qpu_router.select(backend) 
    
    prio_val_any = _PRIO_MAP.get(priority.lower(), priority) 
    prio_val: int
    if isinstance(prio_val_any, str): 
        try: prio_val = int(prio_val_any)
        except ValueError:
            print(f"Warning: Priority string '{priority}' not a recognized name or integer. Defaulting to normal (10).")
            prio_val = _PRIO_MAP.get("normal", 10) 
    elif isinstance(prio_val_any, int): prio_val = prio_val_any
    else: 
        print(f"Warning: Priority '{priority}' resolved to unexpected type. Defaulting to normal (10).")
        prio_val = _PRIO_MAP.get("normal", 10)

    job_id = job_queue.enqueue(device_cls, circ_qasm, priority=prio_val, max_retries=max_retries)
    submitted_ts = datetime.utcnow().isoformat()
    
    # Ensure the 'qubits' value inserted into DB comes from the final ir_opt or metrics_dict
    db_qubit_count = metrics_dict.get('qubits', ir_opt.qubits) # Prefer metrics, fallback to ir_opt

    db.insert_job(
        {
            "id": job_id,
            "backend": backend,
            "priority": prio_val,
            "submitted": submitted_ts, 
            "gate_count": metrics_dict.get("gate_count"), 
            "depth": metrics_dict.get("circuit_depth"),   
            "qubits": db_qubit_count,      
            "model_path": str(model_path.name), 
        }
    )
    logger.log_submit(job_id, backend, circ_qasm, metrics_dict, model_name=model_path.name)
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
    One-shot execution: dispatches a job, waits for completion, optionally logs,
    and returns the backend result or the exception if the job failed.
    """
    resolved_model_path: Path = _resolve_path(model_path) 
    print(f"[api/core.py RUN DEBUG] Resolved model path: {resolved_model_path}") 

    job_id = dispatch(resolved_model_path, backend, priority=priority, max_retries=max_retries)
    result = job_queue.wait(job_id) 
    
    job_details_from_db = db.get_job_by_id(job_id) 
    submitted_iso_timestamp = job_details_from_db.get("submitted") if job_details_from_db else None
    
    current_time_utc = datetime.utcnow()
    completion_time_iso = current_time_utc.isoformat() 

    if not isinstance(result, Exception): 
        completion_status = "completed"
        db.update_job(
            job_id=job_id, 
            status=completion_status, 
            completed=completion_time_iso, 
            result_summary=str(result)[:200] 
        )
        if monitor:
            logger.log_complete(job_id, result, submitted_iso_timestamp, completion_time=current_time_utc)
    else: 
        completion_status = "failed"
        db.update_job(
            job_id=job_id, 
            status=completion_status, 
            completed=completion_time_iso, 
            error_message=str(result) 
        )
        if monitor:
            logger.log_error(job_id, str(result), submitted_iso_timestamp, error_time=current_time_utc)
    
    if monitor: 
        logs(job_id) 

    return result 

def logs(job_id: str) -> None:
    logger.pretty(job_id)


