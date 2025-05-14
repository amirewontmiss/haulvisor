# ~/haulvisor_project/haulvisor/compiler/qasm_gen.py
from typing import List
from haulvisor.compiler.parser import Gate, CircuitIR, GateParams # Ensure GateParams is imported

OPENQASM_HEADER_V2 = """OPENQASM 2.0;
include "qelib1.inc";
"""

def _emit_gate(gate_obj: Gate, num_qubits_in_circuit: int) -> str: # Renamed 'g' to 'gate_obj' for clarity
    """
    Generates an OpenQASM 2.0 string for a single gate.
    Assumes gate_obj.op is already uppercased by the parser.
    """
    op_lower = gate_obj.op.lower()

    # Gates without parameters or with fixed structure
    if gate_obj.op == "H":
        return f"h q[{gate_obj.target}];"
    elif gate_obj.op == "X":
        return f"x q[{gate_obj.target}];"
    elif gate_obj.op == "Y":
        return f"y q[{gate_obj.target}];"
    elif gate_obj.op == "Z":
        return f"z q[{gate_obj.target}];"
    elif gate_obj.op == "S":
        return f"s q[{gate_obj.target}];"
    elif gate_obj.op == "SDG":
        return f"sdg q[{gate_obj.target}];"
    elif gate_obj.op == "T":
        return f"t q[{gate_obj.target}];"
    elif gate_obj.op == "TDG":
        return f"tdg q[{gate_obj.target}];"
    elif gate_obj.op == "RESET":
        return f"reset q[{gate_obj.target}];"
    elif gate_obj.op == "CX":
        if gate_obj.control is None: # Should be caught by parser, but good practice
            raise ValueError("CX gate missing control qubit.")
        return f"cx q[{gate_obj.control}],q[{gate_obj.target}];"
    elif gate_obj.op == "CZ":
        if gate_obj.control is None:
            raise ValueError("CZ gate missing control qubit.")
        return f"cz q[{gate_obj.control}],q[{gate_obj.target}];"
    elif gate_obj.op == "CY":
        if gate_obj.control is None:
            raise ValueError("CY gate missing control qubit.")
        return f"cy q[{gate_obj.control}],q[{gate_obj.target}];"
    elif gate_obj.op == "CH":
        if gate_obj.control is None:
            raise ValueError("CH gate missing control qubit.")
        return f"ch q[{gate_obj.control}],q[{gate_obj.target}];" # qelib1.inc may not have ch
    elif gate_obj.op == "SWAP":
        if gate_obj.control is None: # Assuming SWAP uses target and control as the two qubits
            raise ValueError("SWAP gate requires two qubits (use target and control).")
        return f"swap q[{gate_obj.control}],q[{gate_obj.target}];" # qelib1.inc does have swap
    elif gate_obj.op == "CSWAP" or gate_obj.op == "FREDKIN":
         # Needs 3 qubits. Models may need adjustment for 2 controls.
         # Assuming control is one control, target is another, and need a third.
         # For now, let's assume the parser's Gate model is simpler.
         # This part might need more complex qubit handling based on Gate model.
        raise NotImplementedError(f"QASM for {gate_obj.op} with 3 qubits not fully implemented based on current Gate model.")
    elif gate_obj.op == "CCX" or gate_obj.op == "TOFFOLI":
        # Needs 3 qubits.
        raise NotImplementedError(f"QASM for {gate_obj.op} with 3 qubits not fully implemented based on current Gate model.")
    elif gate_obj.op == "MEASURE":
        return f"measure q[{gate_obj.target}] -> c[{gate_obj.target}];" # Assumes one-to-one classical bit mapping
    elif gate_obj.op == "BARRIER":
        # QASM barrier can be on specific qubits or all.
        # If gate_obj.target is always int, it's specific. If it could be list or None for all...
        # For now, assume specific target, or if target is an indicator for "all".
        # For simplicity, let's assume it applies to all qubits if no specific target is usually given by parser,
        # or applies to a specific one if target is set.
        # A common way is `barrier q;` for all qubits.
        # If your parser gives a target for barrier, it might be `barrier q[target];`
        # Let's make it flexible or default to all.
        # For now, applying to all qubits for simplicity if target is not clearly defined for "all qubits"
        qubit_args = ",".join([f"q[{i}]" for i in range(num_qubits_in_circuit)])
        return f"barrier {qubit_args};" # Barrier on all specified qubits in the register 'q'

    # Parameterized gates
    elif gate_obj.op in ("RX", "RY", "RZ", "P", "U1", "CRX", "CRY", "CRZ", "CP", "CPHASE", "CU1"):
        if gate_obj.params is None or not gate_obj.params.params: # GateParams object & its list must exist and be non-empty
            raise ValueError(f"Parameters missing or empty for gate {gate_obj.op} on q[{gate_obj.target}].")
        
        params_list = gate_obj.params.params
        
        # Single parameter gates
        if gate_obj.op in ("RX", "RY", "RZ"):
            if len(params_list) != 1:
                raise ValueError(f"{gate_obj.op} requires 1 parameter, got {len(params_list)}.")
            return f"{op_lower}({params_list[0]}) q[{gate_obj.target}];"
        elif gate_obj.op == "P" or gate_obj.op == "U1": # U1 is (lambda)
            if len(params_list) != 1:
                raise ValueError(f"{gate_obj.op} (phase/u1) requires 1 parameter, got {len(params_list)}.")
            return f"u1({params_list[0]}) q[{gate_obj.target}];" # u1 in qelib1
        
        # Controlled single parameter gates
        elif gate_obj.op in ("CRX", "CRY", "CRZ"):
            if gate_obj.control is None: raise ValueError(f"{gate_obj.op} needs a control qubit.")
            if len(params_list) != 1: raise ValueError(f"{gate_obj.op} requires 1 parameter, got {len(params_list)}.")
            # qelib1.inc doesn't have crx, cry, crz directly. They need to be decomposed or defined.
            # For now, assuming they might be custom or need a custom include.
            # If targeting Qiskit directly, Qiskit knows these. For pure OpenQASM 2, it's an issue.
            # Let's output a common Qiskit-style QASM, assuming a downstream Qiskit process.
            return f"{op_lower}({params_list[0]}) q[{gate_obj.control}],q[{gate_obj.target}];"
        elif gate_obj.op in ("CP", "CPHASE", "CU1"): # Controlled Phase / CU1(lambda)
            if gate_obj.control is None: raise ValueError(f"{gate_obj.op} needs a control qubit.")
            if len(params_list) != 1: raise ValueError(f"{gate_obj.op} requires 1 parameter, got {len(params_list)}.")
            return f"cu1({params_list[0]}) q[{gate_obj.control}],q[{gate_obj.target}];" # cu1 in qelib1

    elif gate_obj.op == "U2": # U2 is (phi, lambda)
        if gate_obj.params is None or not gate_obj.params.params or len(gate_obj.params.params) != 2:
            raise ValueError(f"U2 gate requires 2 parameters. Got: {gate_obj.params.params if gate_obj.params else 'None'}")
        phi, lam = gate_obj.params.params
        return f"u2({phi},{lam}) q[{gate_obj.target}];" # u2 in qelib1

    elif gate_obj.op == "U3" or gate_obj.op == "U": # U3 is (theta, phi, lambda)
        if gate_obj.params is None or not gate_obj.params.params or len(gate_obj.params.params) != 3:
            raise ValueError(f"{gate_obj.op} gate requires 3 parameters. Got: {gate_obj.params.params if gate_obj.params else 'None'}")
        theta, phi, lam = gate_obj.params.params
        return f"u3({theta},{phi},{lam}) q[{gate_obj.target}];" # u3 in qelib1

    else:
        raise NotImplementedError(f"QASM generation for gate operation '{gate_obj.op}' is not implemented.")

def emit(ir: CircuitIR, qasm_version: int = 2) -> str:
    """
    Generates an OpenQASM string from the CircuitIR.
    """
    if qasm_version != 2:
        raise NotImplementedError(f"QASM version {qasm_version} not supported. Only OpenQASM 2.0.")

    lines: List[str] = []
    lines.append(OPENQASM_HEADER_V2.strip())
    
    lines.append(f"qreg q[{ir.qubits}];")

    # Check if any measure gates exist to determine if creg is needed.
    # Define classical register with the same number of bits as qubits for simplicity.
    # QASM spec requires creg declaration if measure is used.
    has_measure = any(g.op == "MEASURE" for g in ir.gates)
    if has_measure:
        lines.append(f"creg c[{ir.qubits}];")

    for gate_obj in ir.gates:
        try:
            gate_qasm_line = _emit_gate(gate_obj, ir.qubits)
            lines.append(gate_qasm_line)
        except Exception as e:
            # Add more context to errors from _emit_gate
            raise type(e)(f"Error emitting QASM for gate {gate_obj!r}: {e}") from e
            
    return "\n".join(lines) + "\n" # Ensure trailing newline
