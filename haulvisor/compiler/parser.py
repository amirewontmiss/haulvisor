# ~/haulvisor_project/haulvisor/compiler/parser.py
import json
from pathlib import Path
from typing import List, Optional, Union # Make sure Optional is imported

from pydantic import BaseModel, Field, validator, ValidationError # Make sure Field is imported

# Define supported gates (ensure this is comprehensive and matches gate names in JSON after uppercasing)
SUPPORTED_GATES = {
    "H", "X", "Y", "Z", "S", "SDG", "T", "TDG",
    "RX", "RY", "RZ",
    "P", "PHASE", # P and PHASE are common for phase gates (often map to QASM u1)
    "U1", "U2", "U3", "U", # Standard Qiskit/OpenQASM gates
    "CX", "CNOT", # CNOT is an alias for CX
    "CY", "CZ",
    "CH", # Controlled-Hadamard
    "CRX", "CRY", "CRZ", # Controlled Rotations
    "CPHASE", "CP", "CU1", # Controlled Phase
    "SWAP", "CSWAP", "FREDKIN", # SWAP and Controlled-SWAP (Fredkin)
    "CCX", "TOFFOLI", # Toffoli gate (CCNOT)
    "MEASURE",
    "BARRIER",
    "RESET",
    # Add any other gates your system might support
}

class GateParams(BaseModel):
    """
    Represents the parameters for a gate, typically a list of float angles.
    This model corresponds to the inner object in the JSON: "params": [1.047]
    """
    params: List[float] = Field(..., min_items=1)

    class Config:
        extra = "forbid"

class Gate(BaseModel):
    """
    Pydantic model for a single quantum gate from the input JSON.
    """
    op: str
    target: int
    control: Optional[int] = None
    params: Optional[GateParams] = None

    @validator("op", pre=True, always=True)
    def validate_op_name_and_uppercase(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("Gate operation 'op' must be a string.")
        v_upper = v.upper()
        
        alias_map = {
            "CNOT": "CX",
            "TOFFOLI": "CCX",
            "PHASE": "P"
        }
        v_upper = alias_map.get(v_upper, v_upper) # Apply alias

        if v_upper not in SUPPORTED_GATES:
            # Corrected f-string:
            raise ValueError(f"Unsupported gate operation: '{v}'. Supported gates include (partial list): {', '.join(sorted(list(SUPPORTED_GATES))[:10])}...")
        return v_upper

    @validator("params", pre=True)
    def ensure_params_input_is_valid_or_already_processed(cls, v, values): # 'values' is required by Pydantic for some validator types, good to include
        if v is None: # If None is passed, that's fine.
            return None
        if isinstance(v, dict): # If a dictionary is passed (e.g., from JSON), that's fine.
                                # Pydantic will then try to parse this dict into a GateParams object.
            return v
        if isinstance(v, GateParams): # If a GateParams instance is passed (e.g., from optimizer.py),
                                      # that's also fine. Pydantic will use it directly.
            return v
        # If it's something else, it's an error.
        raise ValueError(
            "'params' field for a Gate must be an object (dictionary) to be parsed, "
            "an already formed GateParams instance, or null if not provided."
        )

    @validator("control", always=True)
    def check_control_qubit_for_controlled_gates(cls, v, values):
        op = values.get("op") # 'op' is already validated and uppercased here by the time this validator runs
        controlled_ops = {"CX", "CY", "CZ", "CH", "CRX", "CRY", "CRZ", "CP", "CU1", "CSWAP", "CCX"}
        if op in controlled_ops and v is None:
            raise ValueError(f"Gate '{op}' requires a 'control' qubit.")
        return v
        
    class Config:
        extra = "forbid"

class CircuitIR(BaseModel):
    """
    Pydantic model for the overall circuit intermediate representation, parsed from JSON.
    """
    name: str
    qubits: int = Field(..., gt=0) # Must be greater than 0
    shots: Optional[int] = Field(None, ge=1) # If shots are provided, must be >= 1
    gates: List[Gate]
    depth: Optional[int] = None  # Added field for circuit depth, populated by optimizer

    @validator("gates", each_item=True)
    def check_qubit_indices_in_range(cls, gate: Gate, values):
        """Validate that target and control qubit indices are within the declared qubit range."""
        num_qubits = values.get("qubits")
        if num_qubits is None: # Should not happen if 'qubits' is validated first
            return gate # Or raise an error, but 'qubits' field is mandatory and positive

        if not (0 <= gate.target < num_qubits):
            raise ValueError(
                f"Gate '{gate.op}' target qubit index {gate.target} "
                f"is out of range for {num_qubits} qubits (0 to {num_qubits-1})."
            )
        if gate.control is not None:
            if not (0 <= gate.control < num_qubits):
                raise ValueError(
                    f"Gate '{gate.op}' control qubit index {gate.control} "
                    f"is out of range for {num_qubits} qubits (0 to {num_qubits-1})."
                )
            if gate.control == gate.target: # Control and target cannot be the same qubit
                raise ValueError(
                    f"Gate '{gate.op}': control qubit ({gate.control}) "
                    f"and target qubit ({gate.target}) cannot be the same."
                )
        return gate
        
    class Config:
        extra = "forbid" # No extra fields in the top-level circuit JSON object

def parse(path: Union[str, Path]) -> CircuitIR:
    """
    Parses a JSON circuit description file into a CircuitIR Pydantic model.
    """
    resolved_path = Path(path)
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Circuit JSON file not found at: {resolved_path}")

    with resolved_path.open("r") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format in file {resolved_path}: {e}")

    try:
        circuit_ir_model = CircuitIR(**data)
    except ValidationError as e:
        error_messages = []
        for error in e.errors():
            # Join location tuple items into a string like "field -> index -> subfield"
            loc_str = " -> ".join(map(str, error["loc"]))
            msg = error["msg"]
            error_messages.append(f"Field '{loc_str}': {msg}")
        # Use chr(10) for newline to ensure it works well in different contexts (like logs)
        detailed_errors = chr(10).join(error_messages)
        raise ValueError(
            f"Failed to validate circuit data from {resolved_path} against CircuitIR model.\nDetails:\n{detailed_errors}"
        ) from e
    except Exception as e: # Catch other unexpected errors during instantiation
        raise ValueError(f"Unexpected error creating CircuitIR model from {resolved_path}. Error: {type(e).__name__} - {e}")

    return circuit_ir_model
