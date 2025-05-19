# haulvisor_api/main.py
from __future__ import annotations

import json
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Path as FastApiPath
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ────────────────────────── CONFIG — EDIT HERE ────────────────────────── #

# Origins that are allowed to call the API -------------------------------
LOCAL_DEV_ORIGIN = r"http://localhost:3000"
VERCEL_REGEX     = r"https:\/\/.*\.vercel\.app"

# Path juggling so the Render service finds your internal package --------
PROJECT_ROOT   = Path(__file__).resolve().parent.parent
HAULVISOR_PATH = PROJECT_ROOT / "haulvisor"
sys.path.insert(0, str(HAULVISOR_PATH.parent))

# ───────────────────── TRY REAL HAULVISOR IMPORTS ────────────────────── #

try:
    from haulvisor.api import core as hv_core
    from haulvisor.scheduler import qpu_router as hv_qpu_router
    from haulvisor import db as hv_db
    from haulvisor.monitoring import logger as hv_logger
    print("✅  HaulVisor core imported.")
except Exception as e:  # noqa: BLE001
    print(f"⚠️  HaulVisor import failed → falling back to dummies: {e}")
    print("sys.path =", sys.path)

    class DummyCore:  # type: ignore
        def run(      self, *a, **kw): return {"error": "HaulVisor core not loaded"}
        def dispatch( self, *a, **kw): return "dummy-job-id"
        def logs(     self, *_):       return {}
        def compile(  self, *a, **kw): return "DUMMY QASM"
        def _qasm_version_for_backend(self, *_): return 2
    hv_core = DummyCore()                               # type: ignore[assignment]

    class DummyQPU:                                    # type: ignore
        DEVICE_REGISTRY = {"dummy_backend": None}
    hv_qpu_router = DummyQPU()                          # type: ignore[assignment]

    class DummyDB:                                     # type: ignore
        def get_job_by_id(self, *_): return {}
        def list_jobs(self, *_):    return []
    hv_db = DummyDB()                                   # type: ignore[assignment]

    class DummyLogger:                                 # type: ignore
        LOG_PATH = Path(".")
    hv_logger = DummyLogger()                           # type: ignore[assignment]

# ───────────────────────────── FASTAPI APP ───────────────────────────── #

app = FastAPI(
    title="HaulVisor API",
    description="Quantum circuit orchestration API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    # exact origins you know
    allow_origins=[LOCAL_DEV_ORIGIN],
    # regex that matches all your prod / preview Front-end URLs
    allow_origin_regex=VERCEL_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────── Pydantic Schemas ───────────────────────────── #

class CircuitExecutionRequest(BaseModel):
    circuit_json_str: str
    backend: str = "pennylane"
    priority: str = "normal"
    retries: int = Field(3, ge=0)


class CompileResponse(BaseModel):
    qasm: Optional[str] = None
    error: Optional[str] = None


class RunResponse(BaseModel):
    job_id: Optional[str] = None
    qasm: Optional[str] = None
    logs: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None
    error: Optional[str] = None


class DispatchResponse(BaseModel):
    job_id: str
    message: str
    qasm: Optional[str] = None


class JobStatusData(BaseModel):
    id: Optional[str] = None
    status: Optional[str] = None
    submitted: Optional[str] = None
    completed: Optional[str] = None
    error_message: Optional[str] = None
    result_summary: Optional[str] = None
    model_name: Optional[str] = None
    circ: Optional[str] = None
    gate_count: Optional[int] = None
    circuit_depth: Optional[int] = None
    qubits: Optional[int] = None

    class Config:
        extra = "allow"


class JobStatusResponse(BaseModel):
    job_id: str
    status_data: JobStatusData

# ───────────────────────────── Helpers ───────────────────────────────── #

TEMP_DIR = Path("temp_circuits")
TEMP_DIR.mkdir(exist_ok=True)


def _write_temp_circuit(contents: str) -> Path:
    path = TEMP_DIR / f"temp_{uuid.uuid4()}.json"
    path.write_text(contents)
    return path


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as err:  # noqa: BLE001
        print(f"Could not delete {path}: {err}")

# ─────────────────────────── API Routes ──────────────────────────────── #

@app.get("/")
def root() -> dict[str, str]:
    return {"message": "HaulVisor API up"}


@app.post("/api/compile", response_model=CompileResponse)
def compile_circuit(payload: CircuitExecutionRequest):
    tmp = _write_temp_circuit(payload.circuit_json_str)
    try:
        qasm = hv_core.compile(tmp, backend_hint=payload.backend)
        return CompileResponse(qasm=qasm)
    except Exception as err:  # noqa: BLE001
        traceback.print_exc()
        return CompileResponse(error=str(err))
    finally:
        _safe_unlink(tmp)


@app.post("/api/run", response_model=RunResponse)
def run_circuit(payload: CircuitExecutionRequest):
    tmp = _write_temp_circuit(payload.circuit_json_str)
    try:
        qasm = hv_core.compile(tmp, backend_hint=payload.backend)
        result = hv_core.run(
            model_path=tmp,
            backend=payload.backend,
            priority=payload.priority,
            max_retries=payload.retries,
            monitor=False,
        )
        result_jsonable = result if isinstance(result, (dict, list, str, int, float, bool)) else str(result)
        return RunResponse(qasm=qasm, result=result_jsonable)
    except Exception as err:  # noqa: BLE001
        traceback.print_exc()
        return RunResponse(error=str(err))
    finally:
        _safe_unlink(tmp)


@app.post("/api/dispatch", response_model=DispatchResponse)
def dispatch_circuit(payload: CircuitExecutionRequest):
    tmp = _write_temp_circuit(payload.circuit_json_str)
    try:
        job_id = hv_core.dispatch(
            model_path=tmp,
            backend=payload.backend,
            priority=payload.priority,
            max_retries=payload.retries,
        )
        qasm = hv_core.compile(tmp, backend_hint=payload.backend)
        return DispatchResponse(job_id=job_id, message="Job dispatched", qasm=qasm)
    except Exception as err:  # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(500, str(err))
    finally:
        _safe_unlink(tmp)


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
def job_status(job_id: str = FastApiPath(...)):
    try:
        data_db = hv_db.get_job_by_id(job_id) or {}
        log_path = getattr(hv_logger, "LOG_PATH", Path(".")) / f"{job_id}.json"
        data_log = json.loads(log_path.read_text()) if log_path.exists() else {}
        merged = {**data_db, **data_log}
        return JobStatusResponse(job_id=job_id, status_data=JobStatusData(**merged))
    except Exception as err:  # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(500, str(err))


@app.get("/api/devices", response_model=List[str])
def devices():
    try:
        if hasattr(hv_qpu_router, "DEVICE_REGISTRY"):
            return sorted(hv_qpu_router.DEVICE_REGISTRY)  # type: ignore[arg-type]
        if hasattr(hv_qpu_router, "get_available_devices"):
            return sorted(hv_qpu_router.get_available_devices())  # type: ignore[arg-type]
        return ["pennylane", "qiskit", "braket", "ibm"]
    except Exception as err:  # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(500, str(err))

# ─────────────────────────────────────────────────────────────────────── #
#   Run locally with:   uvicorn haulvisor_api.main:app --reload --port 8000

