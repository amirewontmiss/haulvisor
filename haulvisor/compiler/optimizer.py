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
from typing import List, Dict

from .parser import CircuitIR, Gate

# ─────────────────────────── helpers ─────────────────────────── #

_INV = {
    "X": "X",
    "Y": "Y",
    "Z": "Z",
    "H": "H",
    "T": "TDG",
    "TDG": "T",
    "S": "SDG",
    "SDG": "S",
}

_ROT = {"RX", "RY", "RZ"}

_TWO_PI = 2 * math.pi


def _angles_close(a: float, b: float, tol=1e-8) -> bool:
    return abs(((a - b + math.pi) % _TWO_PI) - math.pi) < tol


# ─────────────────────────── public API ─────────────────────────── #


def optimize(ir: CircuitIR) -> CircuitIR:
    gates = ir.gates
    gates = _cancel_inverses(gates)
    gates = _fuse_rotations(gates)
    gates = _commute_rotations(gates)
    gates, mapping = _qubit_remap(gates)
    ir.gates = gates
    ir.qubits = len(mapping)  # may shrink
    ir.depth = _count_depth(gates)
    return ir


# ─────────────────────────── passes ─────────────────────────── #


def _cancel_inverses(gates: List[Gate]) -> List[Gate]:
    out: List[Gate] = []
    for g in gates:
        if out and _INV.get(g.op) == out[-1].op and g.target == out[-1].target:
            out.pop()
            continue
        out.append(g)
    return out


def _fuse_rotations(gates: List[Gate]) -> List[Gate]:
    out: List[Gate] = []
    for g in gates:
        if (
            out
            and g.op in _ROT
            and g.op == out[-1].op
            and g.target == out[-1].target
        ):
            prev = out[-1]
            prev.params["theta"] = (
                prev.params.get("theta", 0.0) + g.params.get("theta", 0.0)
            ) % _TWO_PI
            if _angles_close(prev.params["theta"], 0.0):
                out.pop()  # net identity
        else:
            out.append(g)
    return out


def _commute_rotations(gates: List[Gate]) -> List[Gate]:
    """
    Commute single-qubit Z-basis rotations through CX/CZ when permitted.

    Rule examples (big-endian):
        ... CX q[c], q[t]; RZ θ q[c]  →  RZ θ q[c]; CX q[c], q[t] ...
        ... CZ q[c], q[t]; RZ θ q[c]  →  RZ θ q[c]; CZ q[c], q[t]
    """
    i = 0
    while i < len(gates) - 1:
        g1, g2 = gates[i], gates[i + 1]

        if (
            g1.op in {"CX", "CZ"}
            and g2.op == "RZ"
            and g2.target == g1.control  # rotation on control qubit
        ):
            gates[i], gates[i + 1] = g2, g1  # swap
            # try to fuse with previous neighbour
            i = max(i - 1, 0)
            continue
        i += 1
    return _fuse_rotations(gates)  # fuse any new neighbours


def _qubit_remap(gates: List[Gate]) -> tuple[List[Gate], Dict[int, int]]:
    """
    Greedy live-range analysis: reuse lowest-numbered free wire.

    Returns
    -------
    gates : new list with remapped targets / controls
    mapping : original → new wire index
    """
    active: Dict[int, int] = {}
    mapping: Dict[int, int] = {}
    next_wire = 0

    def _alloc(w: int) -> int:
        nonlocal next_wire
        if w not in mapping:
            mapping[w] = next_wire
            next_wire += 1
        return mapping[w]

    new_gates: List[Gate] = []
    for g in gates:
        tgt = _alloc(g.target)
        ctrl = _alloc(g.control) if g.control is not None else None
        new_gates.append(Gate(op=g.op, target=tgt, control=ctrl, params=g.params))
    return new_gates, mapping


def _count_depth(gates: List[Gate]) -> int:
    """
    Very simple ASAP scheduler: depth = max layer index +1.
    One-qubit gates share a layer if on distinct wires;
    two-qubit gates occupy their own layer.
    """
    layer_for_wire: Dict[int, int] = defaultdict(int)
    depth = 0
    for g in gates:
        if g.control is None:  # single-qubit gate
            start = layer_for_wire[g.target]
            layer_for_wire[g.target] = start
            depth = max(depth, start)
        else:  # two-qubit gate
            start = max(layer_for_wire[g.target], layer_for_wire[g.control])
            layer_for_wire[g.target] = layer_for_wire[g.control] = start + 1
            depth = max(depth, start + 1)
    return depth + 1

