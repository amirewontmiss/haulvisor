from abc import ABC, abstractmethod

class HaulDevice(ABC):
    name: str
    max_qubits: int

    @abstractmethod
    def compile(self, circuit_qasm: str):
        ...

    @abstractmethod
    def run(self, compiled):
        ...

    @abstractmethod
    def monitor(self, result):
        ...

DEVICE_REGISTRY = {}
def register(device_cls):
    DEVICE_REGISTRY[device_cls.name] = device_cls
    return device_cls

