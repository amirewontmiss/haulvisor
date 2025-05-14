from .device import HaulDevice, register
from qiskit_ibm_provider import IBMProvider
from qiskit import transpile

import yaml, pathlib, os

# load config
cfg = yaml.safe_load(pathlib.Path(__import__("haulvisor").__file__).parent
                     .joinpath("config","default.yaml").read_text())["ibm"]
os.environ["IBMQ_TOKEN"] = cfg["token"]

@register
class IBMDevice(HaulDevice):
    name = "ibm"
    max_qubits = 27

    def compile(self, qasm: str):
        from qiskit import QuantumCircuit
        qc = QuantumCircuit.from_qasm_str(qasm)
        return qc

    def run(self, circuit):
        provider = IBMProvider(
            token=os.environ["IBMQ_TOKEN"],
            url=cfg["url"],
        )
        backend = provider.get_backend(cfg["backend"])
        job = backend.run(transpile(circuit, backend), shots=cfg["shots"])
        result = job.result()
        return result.get_counts()

    def monitor(self, res):
        return {"shots": sum(res.values()), "counts": res}

