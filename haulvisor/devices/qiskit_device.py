"""
haulvisor.devices.qiskit_device
-------------------------------
Unified Qiskit simulator backend that returns statevectors, with optional noise.
"""

from __future__ import annotations
from importlib import import_module

from qiskit import QuantumCircuit, transpile
from .device import HaulDevice, register
from ..noise import HaulNoiseModel

# Discover Aer / BasicAer backend
_backend = None
_sim_name = None

try:
    # Try modern qiskit-aer
    AerSimulator = import_module("qiskit_aer").AerSimulator
    _backend = AerSimulator()
    _sim_name = "AerSimulator (qiskit-aer)"
except ModuleNotFoundError:
    try:
        # Try legacy qiskit.providers.aer
        AerSimulator = import_module("qiskit.providers.aer").AerSimulator
        _backend = AerSimulator()
        _sim_name = "AerSimulator (legacy)"
    except ModuleNotFoundError:
        try:
            # Fallback to BasicAer
            BasicAer = import_module("qiskit").BasicAer
            _backend = BasicAer.get_backend("statevector_simulator")
            _sim_name = "BasicAer statevector_simulator"
        except (ModuleNotFoundError, AttributeError):
            pass

if _backend is None:
    # If no simulator found, skip registration entirely
    raise RuntimeError("No Qiskit simulator backend available.")


@register
class QiskitSimulatorDevice(HaulDevice):
    """State-vector simulator backend via Qiskit Aer, with noise support."""
    name = "qiskit"
    max_qubits = 32

    def compile(self, qasm: str) -> QuantumCircuit:
        """
        Parse OpenQASM into a Qiskit QuantumCircuit, and request statevector save.
        """
        qc = QuantumCircuit.from_qasm_str(qasm)
        # Ensure we can retrieve the statevector
        try:
            qc.save_statevector()
        except Exception:
            # BasicAer may not support save_statevector(); ignore
            pass
        return qc

    def run(self, circuit: QuantumCircuit):
        """
        Transpile + execute the circuit on AerSimulator, injecting noise if configured.
        """
        # Build noise model if present under `noise.qiskit`
        noise = HaulNoiseModel.for_backend("qiskit")
        noise_model = noise.get_qiskit_noise_model() if noise else None

        job = _backend.run(
            transpile(circuit, _backend),
            shots=1,
            noise_model=noise_model,
        )
        result = job.result()

        # Return the statevector
        try:
            return result.get_statevector()
        except Exception:
            # Some versions require passing the circuit
            return result.get_statevector(circuit)

    def monitor(self, res):
        """
        Provide a summary: length of statevector and which simulator was used.
        """
        return {"vec_len": len(res), "sim_backend": _sim_name}

