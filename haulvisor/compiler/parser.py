# ~/haulvisor_project/haulvisor/compiler/parser.py
import json
from pathlib import Path
from typing import List, Optional, Union, Any, Dict 

# For Pydantic V2
from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    ValidationError
)

# Define supported gates (ensure this is comprehensive and matches gate names in JSON after uppercasing)
SUPPORTED_GATES = {
    "H", "X", "Y", "Z", "S", "SDG", "T", "TDG",
    "RX", "RY", "RZ",
    "P", 
    "U1", "U2", "U3", "U", 
    "CX", 
    "CY", "CZ",
    "CH", 
    "CRX", "CRY", "CRZ", 
    "CPHASE", "CP", "CU1", 
    "SWAP", "CSWAP", 
    "CCX", 
    "MEASURE",
    "BARRIER", # BARRIER is a supported gate
    "RESET",
}

class Gate(BaseModel):
    """
    Pydantic model for a single quantum gate from the input JSON.
    """
    op: str
    # MODIFIED: Target is now optional, especially for gates like BARRIER
    target: Optional[int] = None 
    control: Optional[int] = None 
    params: Optional[Dict[str, Any]] = None 

    model_config = {"extra": "forbid"}

    @field_validator("op", mode='before')
    @classmethod
    def validate_op_name_and_uppercase(cls, v: Any) -> str:
        if not isinstance(v, str):
            raise ValueError("Gate operation 'op' must be a string.")
        v_upper = v.upper()
        
        alias_map = {
            "CNOT": "CX",
            "TOFFOLI": "CCX",
            "PHASE": "P", 
            "FREDKIN": "CSWAP" 
        }
        v_upper = alias_map.get(v_upper, v_upper)

        if v_upper not in SUPPORTED_GATES:
            raise ValueError(
                f"Unsupported gate operation: '{v}'. Supported gates include (partial list): "
                f"{', '.join(sorted(list(SUPPORTED_GATES))[:10])}..."
            )
        return v_upper

    @field_validator('target', 'control')
    @classmethod
    def check_qubit_non_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Qubit indices (target, control) must be non-negative.")
        return v

    @model_validator(mode='after')
    def check_gate_specific_requirements(self) -> 'Gate':
        # Check for target requirement
        # Gates like BARRIER might not need a target.
        # All other gates currently in SUPPORTED_GATES (except BARRIER) require a target.
        if self.op != "BARRIER" and self.target is None:
            raise ValueError(f"Gate '{self.op}' requires a 'target' qubit.")

        # Check for control requirement
        controlled_ops = {"CX", "CY", "CZ", "CH", "CRX", "CRY", "CRZ", "CP", "CU1", "CSWAP", "CCX", "CPHASE"}
        if self.op in controlled_ops and self.control is None:
            raise ValueError(f"Gate '{self.op}' requires a 'control' qubit.")
        
        # Ensure non-controlled gates (that are not BARRIER and require a target)
        # do not have 'control' defined, unless explicitly allowed by their definition.
        # This part can be refined based on specific gate definitions.
        # if self.op not in controlled_ops and self.control is not None:
        #     # Some non-controlled gates might use 'control' for other purposes (e.g. SWAP in some conventions)
        #     # For now, this check is commented out to avoid being too restrictive without full context.
        #     pass

        return self

class CircuitIR(BaseModel):
    """
    Pydantic model for the overall circuit intermediate representation, parsed from JSON.
    """
    name: str
    qubits: int = Field(..., gt=0, description="Number of qubits in the circuit, must be positive.")
    shots: Optional[int] = Field(None, ge=1, description="Number of measurement shots, must be at least 1 if specified.")
    gates: List[Gate]
    depth: Optional[int] = Field(None, ge=0, description="Optional pre-calculated depth of the circuit.") 

    model_config = {"extra": "forbid"}

    @model_validator(mode='after')
    def check_qubit_indices_in_range_and_consistency(self) -> 'CircuitIR':
        num_qubits = self.qubits
        for i, gate in enumerate(self.gates):
            # Validate target qubit if it's specified
            if gate.target is not None: # Target is now Optional[int]
                if not (0 <= gate.target < num_qubits):
                    raise ValueError(
                        f"Gate {i} ('{gate.op}') target qubit index {gate.target} "
                        f"is out of range for {num_qubits} qubits (0 to {num_qubits-1})."
                    )
            # Validate control qubit if it's specified
            if gate.control is not None:
                if not (0 <= gate.control < num_qubits):
                    raise ValueError(
                        f"Gate {i} ('{gate.op}') control qubit index {gate.control} "
                        f"is out of range for {num_qubits} qubits (0 to {num_qubits-1})."
                    )
                # Ensure control and target are different if both are specified
                if gate.target is not None and gate.control == gate.target:
                    raise ValueError(
                        f"Gate {i} ('{gate.op}'): control qubit ({gate.control}) "
                        f"and target qubit ({gate.target}) cannot be the same."
                    )
        return self

def parse(path: Union[str, Path]) -> CircuitIR:
    resolved_path = Path(path) # In api.core, path is already resolved. This is fine for standalone use.
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Circuit JSON file not found at: {resolved_path}")

    with resolved_path.open("r", encoding="utf-8") as f: 
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format in file {resolved_path}: {e}")

    try:
        circuit_ir_model = CircuitIR(**data)
    except ValidationError as e:
        error_messages = []
        for error in e.errors():
            loc_str = " -> ".join(map(str, error.get("loc", ())))
            msg = error.get("msg", "Unknown error")
            error_messages.append(f"Field '{loc_str}': {msg}. Input: {error.get('input')}")
        detailed_errors = "\n".join(error_messages) 
        raise ValueError(
            f"Failed to validate circuit data from {resolved_path} against CircuitIR model.\nDetails:\n{detailed_errors}"
        ) from e
    return circuit_ir_model

