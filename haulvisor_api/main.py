# File: ~/haulvisor_project/haulvisor_api/main.py
import sys
import os
from pathlib import Path
import uuid 
import traceback 
from fastapi import FastAPI, HTTPException, Body, Path as FastApiPath
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, List
import json # For the /api/jobs/{job_id} endpoint

# --- Add HaulVisor to Python Path ---
HAULVISOR_PROJECT_ROOT = Path(__file__).resolve().parent.parent
HAULVISOR_PACKAGE_PATH = HAULVISOR_PROJECT_ROOT / "haulvisor"
sys.path.insert(0, str(HAULVISOR_PACKAGE_PATH.parent))

# Now, import from your HaulVisor library
try:
    from haulvisor.api import core as hv_core
    from haulvisor.scheduler import qpu_router as hv_qpu_router
    from haulvisor import db as hv_db
    from haulvisor.monitoring import logger as hv_logger 
    print("Successfully imported HaulVisor modules.")
except ImportError as e:
    print(f"Error importing HaulVisor modules: {e}")
    print(f"Current sys.path: {sys.path}")
    # Dummy classes for FastAPI to start even if HaulVisor import fails
    class DummyCore:
        def run(self, model_path, backend, priority, max_retries, monitor): return {"error": "HaulVisor core not loaded", "details": str(e)}
        def dispatch(self, model_path, backend, priority, max_retries): return "dummy-job-id-error"
        def logs(self, job_id): print(f"Dummy logs for {job_id}")
        def compile(self, model_path, qasm_version=None, backend_hint=None): return "DUMMY QASM: HaulVisor core not loaded"
        def _qasm_version_for_backend(self, backend): return 2
    hv_core = DummyCore()
    class DummyQPU:
        def get_available_devices(self): return ["dummy_backend (HaulVisor not loaded)"]
        DEVICE_REGISTRY = {"dummy_backend": None}
    hv_qpu_router = DummyQPU()
    class DummyDB:
        def get_job_by_id(self, job_id): return {"id": job_id, "status": "dummy_db_error (HaulVisor not loaded)"}
        def list_jobs(self, limit): return [{"id": "dummy_list_job", "status": "dummy_db_error (HaulVisor not loaded)"}]
    hv_db = DummyDB()
    class DummyLogger: # Dummy logger
        LOG_PATH = Path(".") # Define LOG_PATH for the dummy
    hv_logger = DummyLogger()


app = FastAPI(
    title="HaulVisor API",
    description="API for interacting with the HaulVisor quantum circuit orchestration layer.",
    version="0.1.0"
)

# --- CORS Middleware ---
origins = [
    "http://localhost:3000", 
    "http://localhost",      
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"], 
)

# --- Pydantic Models for Request/Response ---
class CircuitExecutionRequest(BaseModel):
    circuit_json_str: str = Field(..., description="The quantum circuit definition as a JSON string.")
    backend: str = Field(default="pennylane", description="Target backend (e.g., 'pennylane', 'qiskit').")
    priority: str = Field(default="normal", description="Job priority ('high', 'normal', 'low').")
    retries: int = Field(default=3, ge=0, description="Maximum backend retries on error.")

class CompileResponse(BaseModel):
    qasm: Optional[str] = None
    error: Optional[str] = None

class RunResponse(BaseModel):
    job_id: Optional[str] = None 
    qasm: Optional[str] = None
    logs: Optional[Dict[str, Any]] = None 
    result: Optional[Any] = None # This will hold the stringified result for complex objects
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
        extra = 'allow' # Allow extra fields not explicitly defined

class JobStatusResponse(BaseModel):
    job_id: str
    status_data: JobStatusData 

# --- API Endpoints ---

@app.get("/")
async def read_root():
    return {"message": "Welcome to the HaulVisor API"}

@app.post("/api/compile", response_model=CompileResponse)
async def compile_circuit_endpoint(payload: CircuitExecutionRequest):
    temp_dir = Path("temp_circuits")
    temp_dir.mkdir(exist_ok=True)
    # Use a unique filename to avoid collisions if multiple requests come in
    temp_file_path = temp_dir / f"temp_circuit_{uuid.uuid4()}.json" 

    try:
        with open(temp_file_path, "w") as f:
            f.write(payload.circuit_json_str)
        
        qasm_version = hv_core._qasm_version_for_backend(payload.backend) # Assuming this helper exists in core
        
        qasm_code = hv_core.compile( # Assuming compile takes these args
            model_path=temp_file_path,
            qasm_version=qasm_version,
            backend_hint=payload.backend
        )
        return CompileResponse(qasm=qasm_code)
    except Exception as e:
        print("--- ERROR IN /api/compile ---")
        traceback.print_exc()
        return CompileResponse(error=f"Error during compilation: {str(e)}")
    finally:
        if temp_file_path.exists():
            try:
                os.remove(temp_file_path)
            except Exception as e_rm:
                print(f"Error removing temp file {temp_file_path}: {e_rm}")


@app.post("/api/run", response_model=RunResponse)
async def run_circuit_endpoint(payload: CircuitExecutionRequest):
    temp_dir = Path("temp_circuits") 
    temp_dir.mkdir(exist_ok=True)
    temp_file_path = temp_dir / f"temp_circuit_{uuid.uuid4()}.json"

    qasm_code: Optional[str] = None
    run_result_display: Any = None # For the JSON serializable version of the result
    error_message: Optional[str] = None
    
    print(f"[API /api/run] Received request for backend: {payload.backend}") 

    try:
        with open(temp_file_path, "w") as f:
            f.write(payload.circuit_json_str)

        try:
            qasm_code = hv_core.compile(model_path=temp_file_path, backend_hint=payload.backend)
        except Exception as compile_e:
            print(f"--- ERROR DURING QASM COMPILATION IN /api/run (backend: {payload.backend}) ---")
            traceback.print_exc()
            qasm_code = f"Error during QASM compilation: {str(compile_e)}"
            # If compilation fails, we might not want to proceed to run
            # For now, we capture the QASM error and will also capture run error if it occurs

        print(f"[API /api/run] Calling hv_core.run for backend: {payload.backend}") 
        run_result_obj = hv_core.run(
            model_path=temp_file_path,
            backend=payload.backend,
            priority=payload.priority,
            max_retries=payload.retries,
            monitor=False 
        )
        print(f"[API /api/run] hv_core.run completed. Result type: {type(run_result_obj)}") 
        
        if isinstance(run_result_obj, Exception):
            error_message = str(run_result_obj)
            print(f"--- ERROR FROM hv_core.run (backend: {payload.backend}) ---")
            # Optionally, log the full traceback of run_result_obj if desired
            # traceback.print_exception(type(run_result_obj), run_result_obj, run_result_obj.__traceback__)
        else:
            # Convert complex objects to string for JSON serialization
            # This handles Qiskit Statevector, PennyLane results (often dicts/arrays), etc.
            if isinstance(run_result_obj, (dict, list, str, int, float, bool)) or run_result_obj is None:
                run_result_display = run_result_obj
            else:
                # For complex objects like Statevector, convert to string
                run_result_display = str(run_result_obj)
                # If you need a more structured representation of Statevector (e.g., list of lists):
                # if hasattr(run_result_obj, 'data') and callable(getattr(run_result_obj, 'tolist')):
                #    run_result_display = run_result_obj.tolist() # Or .data if it's directly a list/array
                # else:
                #    run_result_display = str(run_result_obj)


    except Exception as e:
        print(f"--- UNEXPECTED ERROR IN /api/run ENDPOINT (backend: {payload.backend}) ---")
        traceback.print_exc() 
        error_message = f"Critical server error processing run request: {str(e)}"
    finally:
        if temp_file_path.exists():
            try:
                os.remove(temp_file_path)
            except Exception as e_rm:
                print(f"Error removing temp file {temp_file_path}: {e_rm}")
    
    print(f"[API /api/run] Sending response: QASM: {'Yes' if qasm_code else 'No'}, Result: {'Yes' if run_result_display else 'No'}, Error: {'Yes' if error_message else 'No'}")
    return RunResponse(
        qasm=qasm_code, 
        result=run_result_display, # Send the stringified or simple type result
        error=error_message
    )

@app.post("/api/dispatch", response_model=DispatchResponse)
async def dispatch_circuit_endpoint(payload: CircuitExecutionRequest):
    temp_dir = Path("temp_circuits")
    temp_dir.mkdir(exist_ok=True)
    temp_file_path = temp_dir / f"temp_circuit_{uuid.uuid4()}.json"
    try:
        with open(temp_file_path, "w") as f:
            f.write(payload.circuit_json_str)

        job_id = hv_core.dispatch(
            model_path=temp_file_path,
            backend=payload.backend,
            priority=payload.priority,
            max_retries=payload.retries
        )
        qasm_code = hv_core.compile(model_path=temp_file_path, backend_hint=payload.backend)
        return DispatchResponse(job_id=job_id, message="Job dispatched successfully.", qasm=qasm_code)
    except Exception as e:
        print("--- ERROR IN /api/dispatch ---")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error dispatching circuit: {str(e)}")
    finally:
        if temp_file_path.exists():
            try:
                os.remove(temp_file_path)
            except Exception as e_rm:
                print(f"Error removing temp file {temp_file_path}: {e_rm}")

@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status_endpoint(job_id: str = FastApiPath(..., description="The ID of the job to retrieve.")):
    try:
        job_data_db = hv_db.get_job_by_id(job_id)
        if not job_data_db:
            raise HTTPException(status_code=404, detail=f"Job ID '{job_id}' not found in database.")
        
        log_data_from_file: Dict[str, Any] = {}
        if hasattr(hv_logger, 'LOG_PATH'):
            log_file_path = hv_logger.LOG_PATH / f"{job_id}.json" 
            if log_file_path.exists():
                try:
                    with open(log_file_path, "r") as f:
                        log_data_from_file = json.load(f)
                except json.JSONDecodeError:
                    print(f"Warning: Could not decode JSON log file for job {job_id}")
                except Exception as e_log: 
                    print(f"Error reading log file for job {job_id}: {e_log}")
        
        combined_data = {**job_data_db, **log_data_from_file}
        # Use Pydantic model to validate and structure the data before sending
        validated_data = JobStatusData(**combined_data).model_dump(exclude_none=True)

        return JobStatusResponse(job_id=job_id, status_data=validated_data)
    except HTTPException: # Re-raise HTTPExceptions directly
        raise 
    except Exception as e:
        print(f"--- ERROR IN /api/jobs/{job_id} ---")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error retrieving job status for '{job_id}': {str(e)}")

@app.get("/api/devices", response_model=List[str])
async def list_devices_endpoint():
    try:
        # Attempt to get devices from QPU router first
        if hasattr(hv_qpu_router, 'DEVICE_REGISTRY') and isinstance(hv_qpu_router.DEVICE_REGISTRY, dict):
             return sorted(list(hv_qpu_router.DEVICE_REGISTRY.keys())) 
        elif hasattr(hv_qpu_router, 'get_available_devices') and callable(hv_qpu_router.get_available_devices):
             return sorted(hv_qpu_router.get_available_devices())
        # Fallback to a default list if dynamic retrieval fails
        print("Warning: Could not dynamically get devices from QPU router. Using default list.")
        return ["pennylane", "qiskit", "braket", "ibm"] 
    except Exception as e:
        print("--- ERROR IN /api/devices ---")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error listing devices: {str(e)}")

# To run this API: uvicorn main:app --reload --port 8000

