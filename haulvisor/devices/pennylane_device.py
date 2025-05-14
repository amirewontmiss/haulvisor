"""
haulvisor.devices.pennylane_device
----------------------------------
PennyLane-based simulator backend with optional noise injection.
"""

from __future__ import annotations
import pennylane as qml

from .device import HaulDevice, register
from ..noise import HaulNoiseModel


@register
class PennyLaneDevice(HaulDevice):
    """State-vector simulator backend via PennyLane."""
    name = "pennylane"
    max_qubits = 32

    def compile(self, qasm: str):
        """
        Parse OpenQASM into a PennyLane QNode, then wrap with noise if configured.
        """
        # Build the noiseless QNode from the QASM
        qnode = qml.from_qasm(qasm)

        # Inject noise if configured in config/default.yaml under `noise.pennylane`
        noise = HaulNoiseModel.for_backend("pennylane")
        if noise:
            qnode = noise.apply_to_pennylane(qnode)

        return qnode

    def run(self, qnode):
        """
        Execute the (possibly noisy) QNode and return its statevector.
        """
        return qnode()

    def monitor(self, res):
        """
        Summarize the result: here we report the length of the statevector.
        """
        return {"vec_len": len(res)}

