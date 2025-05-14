"""
haulvisor.monitoring.metrics
----------------------------
Stateless helpers for basic circuit metrics.

Called once per job *before* execution so we can persist the expected
properties even if the device crashes.
"""

from __future__ import annotations
from typing import Dict
from ..compiler.parser import CircuitIR


def calculate(ir: CircuitIR) -> Dict[str, int]:
    """Return {gate_count, circuit_depth, qubits} for the optimised IR."""
    return {
        "gate_count": len(ir.gates),
        "circuit_depth": getattr(ir, "depth", None) or _fallback_depth(ir),
        "qubits": ir.qubits,
    }


# --------------------------------------------------------------------------- #
# fallback depth if optimiser didn't annotate (shouldn't happen)              #
# --------------------------------------------------------------------------- #
def _fallback_depth(ir: CircuitIR) -> int:
    wire_layer = {}
    depth = 0
    for g in ir.gates:
        if g.control is None:
            l = wire_layer.get(g.target, 0)
            wire_layer[g.target] = l
            depth = max(depth, l)
        else:
            start = max(wire_layer.get(g.target, 0), wire_layer.get(g.control, 0))
            wire_layer[g.target] = wire_layer[g.control] = start + 1
            depth = max(depth, start + 1)
    return depth + 1

