"""
haulvisor.noise
---------------
Unified noise-model support for PennyLane and Qiskit backends.
Reads `noise` section from config/default.yaml.
"""

from __future__ import annotations
import yaml
import pathlib
from typing import Any, Dict, Optional, Callable

# PennyLane imports
try:
    import pennylane as qml
    from pennylane.transforms import transform
except ImportError:
    qml = None  # PennyLane not installed

# Qiskit Aer noise imports
try:
    from qiskit.providers.aer.noise import NoiseModel, depolarizing_error, ReadoutError
except ImportError:
    NoiseModel = None
    depolarizing_error = None
    ReadoutError = None

# ── Load noise config ─────────────────────────────────────────────────────── #
_config_path = (
    pathlib.Path(__import__("haulvisor").__file__)
    .parent
    .joinpath("config", "default.yaml")
)
_NOISE_CFG: Dict[str, Any] = yaml.safe_load(_config_path.read_text()).get("noise", {})


class HaulNoiseModel:
    """
    Encapsulates a noise model for a given backend.
    """

    def __init__(self, model: str, params: Dict[str, Any]):
        self.model = model
        self.params = params

    @staticmethod
    def for_backend(backend: str) -> Optional[HaulNoiseModel]:
        """
        Return a HaulNoiseModel if config exists for this backend.
        """
        cfg = _NOISE_CFG.get(backend.lower())
        if cfg and "model" in cfg:
            return HaulNoiseModel(cfg["model"], cfg.get("params", {}))
        return None

    def apply_to_pennylane(self, qnode: Callable) -> Callable:
        """
        Wrap a PennyLane QNode to inject noise after each operation.
        Supported models: 'depolarizing'
        """
        if qml is None:
            raise RuntimeError("PennyLane not installed; cannot apply PennyLane noise model.")

        model = self.model
        params = self.params

        @transform
        def _inject_noise(tape, *args, **kwargs) -> tuple[list, list]:
            new_ops = []
            for op in tape.operations:
                new_ops.append(op)
                if model == "depolarizing":
                    p = float(params.get("p", 0.0))
                    for w in op.wires:
                        new_ops.append(qml.DepolarizingChannel(p, wires=w))
            # Leave measurements untouched
            return new_ops, tape.measurements

        return _inject_noise(qnode)

    def get_qiskit_noise_model(self) -> Optional[NoiseModel]:
        """
        Construct a Qiskit NoiseModel or return None if Aer not installed.
        Supported models: 'depolarizing', 'readout'
        """
        if NoiseModel is None:
            # Aer not available
            return None

        nm = NoiseModel()

        if self.model == "depolarizing":
            p = float(self.params.get("p", 0.0))
            err1 = depolarizing_error(p, 1)
            err2 = depolarizing_error(p, 2)
            nm.add_all_qubit_quantum_error(err1, ["u1", "u2", "u3", "rz", "rx", "ry"])
            nm.add_all_qubit_quantum_error(err2, ["cx", "cnot"])

        if self.model == "readout":
            r = float(self.params.get("readout_error", 0.0))
            ro_err = ReadoutError([[1 - r, r], [r, 1 - r]])
            nm.add_all_qubit_readout_error(ro_err)

        return nm

