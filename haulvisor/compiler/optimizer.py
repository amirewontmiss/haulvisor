"""
haulvisor.compiler.optimizer
----------------------------
Depth-aware optimiser for CircuitIR.

Pipeline:
    GateList  ── P1 cancel inverses
              ── P2 fuse rotations
              ── P3 commute rotations across CNOT/CZ
              ── P4 qubit re-mapping (greedy)
              ── P5 depth counting  →  ir.depth
"""

from __future__ import annotations
import math
from collections import defaultdict
from typing import List, Dict, Optional, Tuple # Added Optional, Tuple

from .parser import CircuitIR, Gate # Assuming Gate and CircuitIR are correctly imported

# ─────────────────────────── helpers ─────────────────────────── #

_INV = {
    "X": "X", "Y": "Y", "Z": "Z", "H": "H",
    "T": "TDG", "TDG": "T",
    "S": "SDG", "SDG": "S",
}

_ROT = {"RX", "RY", "RZ"}
_TWO_PI = 2 * math.pi

def _angles_close(a: float, b: float, tol=1e-8) -> bool:
    return abs(((a - b + math.pi) % _TWO_PI) - math.pi) < tol

# ─────────────────────────── public API ─────────────────────────── #

def optimize(ir: CircuitIR) -> CircuitIR:
    """
    Applies a series of optimization passes to the circuit.
    The number of qubits in the IR might be reduced by the remapping pass.
    """
    gates = ir.gates
    original_qubit_count = ir.qubits # Store for context

    # Apply optimization passes
    gates = _cancel_inverses(gates)
    gates = _fuse_rotations(gates)
    gates = _commute_rotations(gates)
    
    # Qubit remapping pass
    # It returns the new list of gates and the count of unique new wire indices used.
    gates, new_qubit_count_after_remap = _qubit_remap(gates) 
    
    ir.gates = gates
    
    # Update qubit count based on remapping.
    # If remapping results in 0 qubits used (e.g., empty circuit or only global barriers that were skipped),
    # but the original circuit had >0 qubits, we might want to preserve original_qubit_count.
    # However, the primary goal here is to reflect the actual number of wires needed by the remapped gates.
    if new_qubit_count_after_remap > 0:
        ir.qubits = new_qubit_count_after_remap
    elif not gates: # No gates left after optimization
        # If original circuit had qubits, it's now an empty circuit on those qubits.
        # If original also had 0, it remains 0.
        ir.qubits = original_qubit_count if original_qubit_count > 0 else 0
    else: # new_qubit_count_after_remap is 0, but there are gates (e.g., only global BARRIERs that use ir.qubits)
          # In this specific case, if all operations are global, the number of qubits
          # conceptually remains the original count for those global operations.
          # However, if all qubit-specific gates were removed, and only global BARRIERs remain,
          # and if those BARRIERs are later skipped by qasm_gen for some backends,
          # the effective qubit count for QASM generation might still be 0 from qasm_gen's perspective.
          # For now, if remapping says 0 qubits are actively used by specific targets/controls,
          # let's set it to 0, unless it's an empty gate list scenario.
          # The critical fix is to prevent an *increase* in qubit count.
        is_only_global_barriers = all(g.op == "BARRIER" and g.target is None for g in gates)
        if is_only_global_barriers and original_qubit_count > 0:
            ir.qubits = original_qubit_count # Preserve for global barriers
        else:
            ir.qubits = new_qubit_count_after_remap # Typically 0 if no wires were mapped

    # Recalculate depth with the potentially updated qubit count
    ir.depth = _count_depth(gates, ir.qubits) 
    return ir

# ─────────────────────────── passes ─────────────────────────── #

def _cancel_inverses(gates: List[Gate]) -> List[Gate]:
    out: List[Gate] = []
    for g in gates:
        # Check for inverse only if 'out' is not empty and params are None (for non-parameterized inverses)
        if (out and 
            _INV.get(g.op) == out[-1].op and 
            g.target == out[-1].target and 
            g.control == out[-1].control and # Ensure control qubits also match
            g.params is None and out[-1].params is None): # Only cancel non-parameterized gates this way
            out.pop()
        else:
            out.append(g)
    return out

def _fuse_rotations(gates: List[Gate]) -> List[Gate]:
    out: List[Gate] = []
    for g in gates:
        if (out and 
            g.op in _ROT and 
            g.op == out[-1].op and 
            g.target == out[-1].target and
            g.control == out[-1].control and # Rotations are single-qubit, control should be None
            g.params and out[-1].params): # Both must have params
            
            prev_gate = out[-1]
            # Ensure 'theta' exists and sum params
            current_theta = g.params.get("theta", 0.0)
            prev_theta = prev_gate.params.get("theta", 0.0)
            new_theta = (prev_theta + current_theta) % _TWO_PI
            
            if _angles_close(new_theta, 0.0): # If sum is close to 0 (or 2*pi), effectively an identity
                out.pop() 
            else:
                prev_gate.params["theta"] = new_theta # Update existing gate's theta
        else:
            out.append(g)
    return out

def _commute_rotations(gates: List[Gate]) -> List[Gate]:
    """
    Commute single-qubit Z-basis rotations through CX/CZ when permitted.
    """
    i = 0
    made_change_in_pass = True # Flag to re-run fusion if changes were made
    
    # This loop structure can be complex to get right for multiple passes.
    # A simpler approach might be a single pass of commutation, then re-run fusion.
    # For now, keeping original logic but noting potential for infinite loops if i is reset too aggressively.
    while i < len(gates) - 1:
        g1, g2 = gates[i], gates[i + 1]

        # Rule: CX(c,t); RZ(theta) q[c]  ->  RZ(theta) q[c]; CX(c,t)
        # Rule: CZ(c,t); RZ(theta) q[c]  ->  RZ(theta) q[c]; CZ(c,t)
        # Rule: CZ(c,t); RZ(theta) q[t]  ->  RZ(theta) q[t]; CZ(c,t) (CZ is symmetric)
        can_commute = False
        if g1.op in {"CX", "CZ"} and g2.op == "RZ":
            if g2.target == g1.control: # RZ on control of CX or CZ
                can_commute = True
            elif g1.op == "CZ" and g2.target == g1.target: # RZ on target of CZ
                can_commute = True
        
        if can_commute:
            gates[i], gates[i + 1] = g2, g1  # Swap
            # After a swap, the RZ gate might be able to fuse with a preceding RZ.
            # Restarting scan or going back one step is common.
            # The original `i = max(i - 1, 0)` ensures we re-check the new g2's position.
            i = max(i - 2, 0) # Go back further to potentially catch more fusions if g2 moved left
            continue # Restart loop from new 'i'
        i += 1
        
    return _fuse_rotations(gates) # Fuse any newly adjacent rotations

def _qubit_remap(gates: List[Gate]) -> Tuple[List[Gate], int]:
    """
    Greedy live-range analysis: reuse lowest-numbered free wire.
    Returns the new list of gates and the count of unique new wire indices used.
    """
    mapping: Dict[int, int] = {} # original_wire_idx -> new_wire_idx
    next_new_wire_idx = 0 # Counter for assigning new, compact wire indices

    def _get_or_alloc_new_wire(original_wire_idx: int) -> int:
        """Allocates a new compact wire index if original_wire_idx hasn't been seen."""
        nonlocal next_new_wire_idx
        if original_wire_idx not in mapping:
            mapping[original_wire_idx] = next_new_wire_idx
            next_new_wire_idx += 1
        return mapping[original_wire_idx]

    new_gates: List[Gate] = []
    for g in gates:
        new_target: Optional[int] = None
        if g.target is not None: # Process target only if it's an actual qubit index
            new_target = _get_or_alloc_new_wire(g.target)

        new_control: Optional[int] = None
        if g.control is not None: # Process control only if it's an actual qubit index
            new_control = _get_or_alloc_new_wire(g.control)
        
        # Create new gate with potentially remapped target/control.
        # BARRIER with target=None will have new_target=None.
        new_gates.append(Gate(op=g.op, target=new_target, control=new_control, params=g.params))
    
    # The number of unique new wire indices assigned is simply next_new_wire_idx
    return new_gates, next_new_wire_idx


def _count_depth(gates: List[Gate], num_qubits: int) -> int:
    """
    Calculates circuit depth using an ASAP (As Soon As Possible) scheduling model.
    Assumes single-qubit and two-qubit gates take one time step.
    """
    # layer_busy_until[qubit_index] = k means qubit_index is busy until the end of layer k-1
    # (i.e., it becomes free at the beginning of layer k).
    layer_busy_until: Dict[int, int] = defaultdict(int)
    max_depth_achieved = 0

    if not gates:
        return 0 # An empty circuit has zero depth

    for g in gates:
        if g.op == "BARRIER" and g.target is None: # Global barrier
            # A global barrier synchronizes all qubits.
            # All qubits become busy until the end of the layer defined by the latest finishing qubit.
            current_max_layer_busy = 0
            if layer_busy_until: # Check if any operations happened before
                current_max_layer_busy = max(layer_busy_until.values()) if layer_busy_until else 0
            
            barrier_ends_at_layer = current_max_layer_busy + 1
            for i in range(num_qubits):
                layer_busy_until[i] = barrier_ends_at_layer
            max_depth_achieved = max(max_depth_achieved, barrier_ends_at_layer)
            continue

        # For gates acting on specific qubits
        # Target must exist for non-global BARRIER ops (ensured by parser or Gate model validation)
        if g.target is None: 
            # This should ideally not be reached if parser validates target for non-BARRIER ops
            # Or if BARRIER with specific target is handled differently.
            # For safety, skip if target is unexpectedly None for an op that needs it.
            print(f"Warning: Gate {g.op} has None target in depth calculation, skipping.")
            continue
            
        if g.control is None:  # Single-qubit gate
            start_execution_at_layer = layer_busy_until[g.target]
            gate_finishes_at_layer = start_execution_at_layer + 1
            layer_busy_until[g.target] = gate_finishes_at_layer
            max_depth_achieved = max(max_depth_achieved, gate_finishes_at_layer)
        else:  # Two-qubit gate
            start_execution_at_layer = max(layer_busy_until[g.target], layer_busy_until[g.control])
            gate_finishes_at_layer = start_execution_at_layer + 1
            layer_busy_until[g.target] = gate_finishes_at_layer
            layer_busy_until[g.control] = gate_finishes_at_layer
            max_depth_achieved = max(max_depth_achieved, gate_finishes_at_layer)
            
    return max_depth_achieved

