from ..devices import DEVICE_REGISTRY
# ensure BraketDevice is loaded
try:
    import haulvisor.devices.braket_device  # noqa: F401
except ImportError:
    pass

try:
    import haulvisor.devices.ibm_device  # noqa
except ImportError:
    pass

def select(name: str):
    return DEVICE_REGISTRY[name]

