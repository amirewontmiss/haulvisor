# ~/haulvisor_project/haulvisor/noise.py
"""
haulvisor.noise
---------------
Unified noise-model support for PennyLane and Qiskit backends.
Reads `noise` section from config/default.yaml.
"""

from __future__ import annotations
import yaml
import pathlib
from typing import Any, Dict, Optional, Callable, List as TypingList

# PennyLane imports
try:
    import pennylane as qml
    from pennylane.transforms import transform
    from pennylane.tape import QuantumTape # For type hinting
    import pennylane.operation # For type hinting Operation
    import pennylane.measurements # For type hinting MeasurementProcess
except ImportError:
    qml = None
    transform = None
    QuantumTape = None # Define for type hinting even if not available
    pennylane = None # to allow attribute access like pennylane.operation

# Qiskit Aer noise imports
try:
    from qiskit.providers.aer.noise import NoiseModel, depolarizing_error, ReadoutError
except ImportError:
    NoiseModel = None
    depolarizing_error = None
    ReadoutError = None

_config_file_path = (
    pathlib.Path(__file__) # Path to current noise.py (haulvisor_project/haulvisor/noise.py)
    .parent # Up to haulvisor_project/haulvisor/
    .joinpath("config", "default.yaml") # Correctly looks for haulvisor_project/haulvisor/config/default.yaml
)

_NOISE_CFG: Dict[str, Any] = {}
if _config_file_path.exists():
    try:
        _NOISE_CFG = yaml.safe_load(_config_file_path.read_text()).get("noise", {})
    except Exception as e:
        print(f"Warning: Could not load or parse noise config from {_config_file_path}: {e}")
else:
    print(f"Warning: Noise config file not found at {_config_file_path}")


class HaulNoiseModel:
    """
    Encapsulates a noise model for a given backend.
    """
    def __init__(self, model_type: str, params: Dict[str, Any]):
        self.model_type = model_type
        self.params = params

    @staticmethod
    def for_backend(backend: str) -> Optional[HaulNoiseModel]:
        cfg = _NOISE_CFG.get(backend.lower())
        if cfg and "model" in cfg:
            return HaulNoiseModel(cfg["model"], cfg.get("params", {}))
        return None

    def apply_to_pennylane(self, qfunc: Callable) -> Callable:
        if qml is None or transform is None:
            raise RuntimeError("PennyLane not installed; cannot apply PennyLane noise model.")

        print("DEBUG HNM: apply_to_pennylane called. Using PASS-THROUGH _inject_noise for debugging.")

        @transform
        def _inject_noise_passthrough(tape: QuantumTape, *args, **kwargs) -> tuple[TypingList[pennylane.operation.Operation], TypingList[pennylane.measurements.MeasurementProcess]]:
            """
            DEBUGGING VERSION: This transform does nothing to the tape.
            It just returns the original operations and measurements.
            """
            print(f"DEBUG HNM _inject_noise_passthrough: Original tape.operations: {tape.operations}")
            print(f"DEBUG HNM _inject_noise_passthrough: Original tape.measurements: {tape.measurements}")
            return tape.operations, tape.measurements # Pass-through

        # Apply the pass-through transform
        return _inject_noise_passthrough(qfunc)

    def get_qiskit_noise_model(self) -> Optional[NoiseModel]:
        if NoiseModel is None or depolarizing_error is None or ReadoutError is None:
            return None

        qiskit_nm = NoiseModel()
        noise_added = False

        if self.model_type == "depolarizing":
            p = float(self.params.get("p", 0.0))
            if p > 0:
                error1 = depolarizing_error(p, 1)
                error2 = depolarizing_error(p, 2)
                qiskit_nm.add_all_qubit_quantum_error(error1, ["u1", "u2", "u3", "rz", "sx", "x", "p", "id", "h", "s", "sdg", "t", "tdg", "ry"])
                qiskit_nm.add_all_qubit_quantum_error(error2, ["cx", "ecr", "cz", "swap"])
                noise_added = True

        if self.model_type == "readout":
            r = float(self.params.get("readout_error_prob", self.params.get("r", 0.0)))
            if r > 0:
                prob_matrix = [[1 - r, r], [r, 1 - r]]
                readout_error_op = ReadoutError(prob_matrix)
                qiskit_nm.add_all_qubit_readout_error(readout_error_op)
                noise_added = True
        
        return qiskit_nm if noise_added else None
