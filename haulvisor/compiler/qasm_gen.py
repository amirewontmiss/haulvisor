# ~/haulvisor_project/haulvisor/compiler/qasm_gen.py
from typing import List, Dict, Any, Optional 
import math # For pi

from haulvisor.compiler.parser import Gate, CircuitIR 

OPENQASM_HEADER_V2 = """OPENQASM 2.0;
include "qelib1.inc";
"""

def _get_param(params_dict: Optional[Dict[str, Any]], key: str, gate_op_for_error: str, default: Optional[Any] = None) -> float:
    """Helper to get a float parameter from the params dictionary or raise/return default."""
    if params_dict is None:
        if default is not None: 
            return float(default) 
        raise ValueError(f"Parameters dictionary is None for gate {gate_op_for_error} requiring parameter '{key}'.")
    
    param_val = params_dict.get(key)
    if param_val is None:
        if default is not None: 
            return float(default)
        raise ValueError(f"Required parameter '{key}' not found for gate {gate_op_for_error}. Available params: {list(params_dict.keys())}") 
    
    if not isinstance(param_val, (int, float)):
        raise ValueError(f"Parameter '{key}' for gate {gate_op_for_error} must be a number, got {type(param_val)}.")
    return float(param_val)

def _emit_gate(gate_obj: Gate, num_qubits_in_circuit: int, backend_hint: Optional[str] = None) -> str:
    """
    Generates an OpenQASM 2.0 string for a single gate.
    Uses backend_hint to adjust QASM for specific backends (e.g., Braket).
    Returns an empty string for gates that should be skipped for a given backend.
    """
    op_lower = gate_obj.op.lower()
    is_braket = backend_hint and "braket" in backend_hint.lower()

    # --- DEBUG PRINT ---
    # if gate_obj.op in ("P", "U1", "U2", "U3", "CP", "CPHASE", "CU1", "BARRIER", "RESET"):
    #     print(f"[qasm_gen DEBUG] Gate: {gate_obj.op}, Backend Hint: '{backend_hint}', is_braket: {is_braket}")
    # --- END DEBUG PRINT ---

    target_qubit = gate_obj.target # Can be None for BARRIER if applied to all
    if target_qubit is None and gate_obj.op not in ("BARRIER"):
        raise ValueError(f"Target qubit is None for gate '{gate_obj.op}' which requires a target.")

    # Handle BARRIER specifically for Braket
    if gate_obj.op == "BARRIER":
        if is_braket:
            print(f"[qasm_gen INFO] Skipping BARRIER instruction for Braket backend.")
            return "" # Omit barrier for Braket
        elif gate_obj.target is not None: 
            return f"barrier q[{gate_obj.target}];"
        else: 
            qubit_args = ",".join([f"q[{i}]" for i in range(num_qubits_in_circuit)])
            return f"barrier {qubit_args};"

    # Handle RESET specifically for Braket
    if gate_obj.op == "RESET":
        if is_braket:
            print(f"[qasm_gen INFO] Skipping RESET instruction for Braket backend.")
            return "" # Omit reset for Braket
        else:
            return f"{op_lower} q[{target_qubit}];"

    # Non-parameterized gates (excluding BARRIER and RESET already handled)
    if gate_obj.op in ("H", "X", "Y", "Z", "S", "SDG", "T", "TDG"):
        return f"{op_lower} q[{target_qubit}];"
    elif gate_obj.op in ("CX", "CY", "CZ", "CH"):
        if gate_obj.control is None: raise ValueError(f"{gate_obj.op} gate missing control qubit.")
        return f"{op_lower} q[{gate_obj.control}],q[{target_qubit}];"
    elif gate_obj.op == "SWAP":
        if gate_obj.control is None: raise ValueError("SWAP gate requires two qubits; 'control' field used for the second qubit.")
        return f"swap q[{target_qubit}],q[{gate_obj.control}];" 
    elif gate_obj.op == "MEASURE":
        return f"measure q[{target_qubit}] -> c[{target_qubit}];"
    
    # Parameterized Gates - ensure params exist
    if gate_obj.params is None: # Should be caught by parser if params are mandatory for the op
        raise ValueError(f"Parameters dictionary is missing for parameterized gate {gate_obj.op}.")

    if gate_obj.op in ("RX", "RY", "RZ"):
        theta = _get_param(gate_obj.params, "theta", gate_obj.op)
        return f"{op_lower}({theta}) q[{target_qubit}];"
    
    elif gate_obj.op == "P": 
        lambda_param = _get_param(gate_obj.params, "theta", gate_obj.op) 
        if is_braket:
            return f"phaseshift({lambda_param}) q[{target_qubit}];" 
        else:
            return f"u1({lambda_param}) q[{target_qubit}];"      
    elif gate_obj.op == "U1":
        lambda_param = _get_param(gate_obj.params, "lambda", gate_obj.op)
        if is_braket:
            return f"phaseshift({lambda_param}) q[{target_qubit}];"
        else:
            return f"u1({lambda_param}) q[{target_qubit}];"

    elif gate_obj.op in ("CRX", "CRY", "CRZ"):
        if gate_obj.control is None: raise ValueError(f"{gate_obj.op} gate missing control qubit.")
        theta = _get_param(gate_obj.params, "theta", gate_obj.op)
        return f"{op_lower}({theta}) q[{gate_obj.control}],q[{target_qubit}];"
    elif gate_obj.op in ("CP", "CPHASE"): 
        if gate_obj.control is None: raise ValueError(f"{gate_obj.op} gate missing control qubit.")
        lambda_param = _get_param(gate_obj.params, "theta", gate_obj.op)
        if is_braket:
            return f"cphaseshift({lambda_param}) q[{gate_obj.control}],q[{target_qubit}];"
        else:
            return f"cu1({lambda_param}) q[{gate_obj.control}],q[{target_qubit}];"
    elif gate_obj.op == "CU1":
        if gate_obj.control is None: raise ValueError(f"{gate_obj.op} gate missing control qubit.")
        lambda_param = _get_param(gate_obj.params, "lambda", gate_obj.op)
        if is_braket:
            return f"cphaseshift({lambda_param}) q[{gate_obj.control}],q[{target_qubit}];"
        else:
            return f"cu1({lambda_param}) q[{gate_obj.control}],q[{target_qubit}];"

    elif gate_obj.op == "U2":
        phi = _get_param(gate_obj.params, "phi", gate_obj.op)
        lam = _get_param(gate_obj.params, "lambda", gate_obj.op)
        if is_braket:
            q = f"q[{target_qubit}]"
            # U2(phi, lambda) = Rz(lambda) Ry(pi/2) Rz(phi)
            # Based on common Qiskit definition U2(φ,λ) = U(π/2,φ,λ)
            # And U(θ,φ,λ) = Rz(φ) Ry(θ) Rz(λ) is a common convention (differs from qelib1.inc)
            # If using qelib1.inc U(θ,φ,λ) = Rz(λ) Rx(π/2) Rz(θ) Rx(-π/2) Rz(φ)
            # U2(φ,λ) = U(π/2,φ,λ) = Rz(λ) Rx(π/2) Rz(π/2) Rx(-π/2) Rz(φ)
            # Let's use a simpler decomposition for Braket: Rz(phi) Ry(pi/2) Rz(lambda)
            # This is equivalent to U(pi/2, phi, lambda) in Qiskit's U definition.
            # Or more directly, many systems define U2(phi, lambda) = Rz(phi) S Rz(lambda) H, but S is not native in Braket.
            # Using Rz Ry Rz decomposition:
            return (f"rz({phi}) {q};\n"
                    f"ry({math.pi/2}) {q};\n"
                    f"rz({lam}) {q};")
        else:
            return f"u2({phi},{lam}) q[{target_qubit}];"

    elif gate_obj.op == "U3" or gate_obj.op == "U":
        theta = _get_param(gate_obj.params, "theta", gate_obj.op)
        phi = _get_param(gate_obj.params, "phi", gate_obj.op)
        lam = _get_param(gate_obj.params, "lambda", gate_obj.op)
        if is_braket:
            # Decompose U3(theta, phi, lambda) into Rz, Ry, Rz for Braket
            # U(θ,φ,λ) = Rz(φ) Ry(θ) Rz(λ) (common convention)
            q = f"q[{target_qubit}]"
            return (f"rz({phi}) {q};\n"
                    f"ry({theta}) {q};\n"
                    f"rz({lam}) {q};")
        else:
            return f"u3({theta},{phi},{lam}) q[{target_qubit}];"

    elif gate_obj.op in ("CSWAP", "CCX"): 
        raise NotImplementedError(f"QASM for {gate_obj.op} needs Gate model enhancements or specific decomposition.")
    else:
        raise NotImplementedError(f"QASM generation for gate operation '{gate_obj.op}' is not implemented.")

def emit(ir: CircuitIR, qasm_version: int = 2, backend_hint: Optional[str] = None) -> str:
    if qasm_version != 2:
        raise NotImplementedError(f"QASM version {qasm_version} not supported. Only OpenQASM 2.0 currently.")

    lines: List[str] = []
    lines.append(OPENQASM_HEADER_V2.strip())
    lines.append(f"qreg q[{ir.qubits}];")

    has_measure = any(g.op == "MEASURE" for g in ir.gates)
    if has_measure:
        lines.append(f"creg c[{ir.qubits}];") 

    for gate_obj in ir.gates:
        try:
            gate_qasm_line = _emit_gate(gate_obj, ir.qubits, backend_hint=backend_hint)
            # Decomposed gates might return multiple lines or an empty string (for skipped gates)
            if gate_qasm_line: # Only append if not an empty string
                for line in gate_qasm_line.strip().split('\n'):
                    if line.strip(): 
                        lines.append(line.strip())
        except Exception as e:
            raise type(e)(
                f"Error emitting QASM for gate op='{gate_obj.op}', "
                f"target={gate_obj.target}, control={gate_obj.control}, params={gate_obj.params}: {e}"
            ) from e
            
    return "\n".join(lines) + "\n"

