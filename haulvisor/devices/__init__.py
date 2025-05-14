"""
haulvisor.devices package

Exposes DEVICE_REGISTRY and eagerly loads built-in back-ends.
"""

from .device import DEVICE_REGISTRY

# ---------- mandatory backend ------------------------------------------------
from .pennylane_device import PennyLaneDevice  # noqa: F401

# ---------- optional qiskit backend ------------------------------------------
try:
    # importing the module is enough—the @register decorator runs on import
    from .qiskit_device import QiskitSimulatorDevice  # noqa: F401
except (ImportError, RuntimeError):
    # SDK not installed or no simulator available; skip silently
    pass

__all__ = ["DEVICE_REGISTRY"]

