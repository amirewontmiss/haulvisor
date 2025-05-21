# ~/haulvisor_project/haulvisor/devices/pennylane_device.py
"""
HaulVisor PennyLane back-end.

Changes versus the previous version
-----------------------------------
1.  *Eagerly* import ``pennylane_qiskit`` so that the QASM loader plugin
    is registered before we call ``qml.from_qasm``.
2.  If that plugin is missing we raise a clear ImportError right away,
    instead of letting PennyLane emit the cryptic
    “Failed to load the qasm plugin” message at runtime.
3.  No other logic has been touched.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Ensure the PennyLane-Qiskit plug-in is present and registered with PennyLane
# --------------------------------------------------------------------------- #
try:
    import pennylane_qiskit  # noqa: F401  (import only for side-effect)
    print("✅  'pennylane-qiskit' plugin imported – PennyLane QASM loader ready.")
except ImportError as err:
    raise ImportError(
        "❌  The 'pennylane-qiskit' package is required for qml.from_qasm().\n"
        "    Add it to requirements.txt (pennylane-qiskit>=0.41) and redeploy."
    ) from err
# --------------------------------------------------------------------------- #

import pennylane as qml
from pennylane import numpy as pnp
from typing import Any, Dict, Optional

from .device import HaulDevice, register
from ..noise import HaulNoiseModel  # (still unused – kept for future work)


@register
class PennyLaneDevice(HaulDevice):
    name = "pennylane"
    max_qubits = 32
    default_shots = 1024

    def __init__(self, shots: int | None = None):
        super().__init__()
        self.shots = shots or self.default_shots
        self.dev: Optional[qml.Device] = None
        self._compiled_qnode: Optional[qml.QNode] = None
        self.num_wires_for_circuit: Optional[int] = None

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #
    @staticmethod
    def _get_num_wires_from_qasm(qasm: str) -> int:
        """Extract qubit count from the first ``qreg`` declaration."""
        for line in qasm.splitlines():
            line = line.strip()
            if line.startswith("qreg"):
                try:
                    size_part = line.split()[1]              # e.g. "q[2];"
                    return int(size_part.split("[")[1].split("]")[0])
                except (IndexError, ValueError) as exc:
                    raise ValueError(
                        f"Malformed qreg declaration in QASM line: '{line}'"
                    ) from exc
        raise ValueError("No qreg declaration found in QASM; cannot infer qubit count.")

    # --------------------------------------------------------------------- #
    # Compile  (QASM ➜ PennyLane QNode)
    # --------------------------------------------------------------------- #
    def compile(self, qasm: str) -> qml.QNode:
        # Parse to a Python callable first
        qfunc_from_qasm = qml.from_qasm(qasm)

        # Determine qubit count and basic sanity-check
        self.num_wires_for_circuit = self._get_num_wires_from_qasm(qasm)
        if not (0 < self.num_wires_for_circuit <= self.max_qubits):
            raise ValueError(
                f"Circuit needs {self.num_wires_for_circuit} qubits but "
                f"PennyLaneDevice supports 1–{self.max_qubits}."
            )

        # Allocate the simulator
        self.dev = qml.device(
            "default.qubit",
            wires=self.num_wires_for_circuit,
            shots=self.shots,
        )

        # Optional noise insertion could go here  –  currently bypassed.
        qfunc_for_decoration = qfunc_from_qasm

        # Wrap into a QNode that returns samples
        @qml.qnode(self.dev)
        def final_circuit_qnode():
            qfunc_for_decoration()
            return qml.sample(wires=range(self.num_wires_for_circuit))

        self._compiled_qnode = final_circuit_qnode
        return final_circuit_qnode

    # --------------------------------------------------------------------- #
    # Run  (execute the compiled QNode)
    # --------------------------------------------------------------------- #
    def run(self, qnode_to_run: qml.QNode) -> Dict[str, int] | Dict[str, Any]:
        if qnode_to_run is None:
            raise ValueError("No QNode supplied – did you call compile()?")

        try:
            raw_results = qnode_to_run()
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"PennyLane execution error: {exc}") from exc

        # Shots-based (sampling) mode
        if self.shots:
            if not isinstance(raw_results, pnp.ndarray):
                return {"error": "Unexpected result type", "raw_result": str(raw_results)}

            if raw_results.ndim == 1:  # single-wire OR single-shot, multi-wire
                samples_str = ["".join(map(str, raw_results.astype(int)))]
            elif raw_results.ndim == 2:  # (shots, wires)
                samples_str = ["".join(map(str, row)) for row in raw_results.astype(int)]
            else:
                return {"error": f"Unexpected sample array dim {raw_results.ndim}"}

            counts: Dict[str, int] = {}
            for sample in samples_str:
                counts[sample] = counts.get(sample, 0) + 1
            return counts

        # Analytic mode
        return {"raw_result": raw_results}

    # --------------------------------------------------------------------- #
    # Monitor – optional post-processing
    # --------------------------------------------------------------------- #
    def monitor(self, res: Any) -> Dict[str, Any]:
        if isinstance(res, dict):
            if all(isinstance(k, str) and isinstance(v, int) for k, v in res.items()):
                total = sum(res.values())
                return {
                    "total_shots_observed": total,
                    "num_unique_outcomes": len(res),
                    "counts": res,
                }
        return {"result_summary": f"Unrecognised result format: {res!r}"}

