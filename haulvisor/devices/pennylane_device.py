# ~/haulvisor_project/haulvisor/devices/pennylane_device.py
from __future__ import annotations
import pennylane as qml
from pennylane import numpy as pnp 
from typing import Callable, Dict, Any, Optional, Union, List
import pennylane_qiskit  
from .device import HaulDevice, register
from ..noise import HaulNoiseModel # Still import it, just won't use it in compile for this test

@register
class PennyLaneDevice(HaulDevice):
    name = "pennylane"
    max_qubits = 32
    default_shots = 1024

    def __init__(self, shots: int | None = None):
        super().__init__()
        self.shots = shots if shots is not None else self.default_shots
        self.dev: Optional[qml.Device] = None 
        self._compiled_qnode: Optional[qml.QNode] = None # Removed _qfunc_from_qasm as it's local to compile
        self.num_wires_for_circuit: Optional[int] = None

    def _get_num_wires_from_qasm(self, qasm: str) -> int:
        for line in qasm.splitlines():
            line = line.strip()
            if line.startswith("qreg"):
                try:
                    name_and_size = line.split(" ")[1]
                    return int(name_and_size.split("[")[1].split("]")[0])
                except (IndexError, ValueError) as e:
                    raise ValueError(f"Malformed qreg declaration in QASM: '{line}'. Error: {e}")
        raise ValueError("Could not determine number of wires from QASM 'qreg' declaration.")

    def compile(self, qasm: str) -> qml.QNode:
        qfunc_from_qasm = qml.from_qasm(qasm) # Fresh parse from QASM

        try:
            self.num_wires_for_circuit = self._get_num_wires_from_qasm(qasm)
        except ValueError as e:
            raise ValueError(f"QASM processing error: {e}. Cannot configure PennyLane device.") from e

        if not (0 < self.num_wires_for_circuit <= self.max_qubits):
            raise ValueError(
                f"Circuit requires {self.num_wires_for_circuit} qubits, "
                f"but PennyLaneDevice supports 1 to {self.max_qubits} qubits."
            )

        self.dev = qml.device("default.qubit", wires=self.num_wires_for_circuit, shots=self.shots)

        # --- COMPLETELY BYPASS NOISE TRANSFORM FOR THIS TEST ---
        print(f"INFO: BYPASSING Haulvisor noise model for PennyLane. Compiling circuit with {self.num_wires_for_circuit} wires.")
        qfunc_for_decoration = qfunc_from_qasm 
        # --- END BYPASS ---
            
        @qml.qnode(self.dev)
        def final_circuit_qnode():
            qfunc_for_decoration() 
            return qml.sample(wires=range(self.num_wires_for_circuit))

        self._compiled_qnode = final_circuit_qnode
        return self._compiled_qnode

    # run() and monitor() methods remain the same
    def run(self, qnode_to_run: qml.QNode) -> Dict[str, int]:
        if qnode_to_run is None:
            raise ValueError("Invalid QNode passed to run method. Ensure compile() was successful and returned a QNode.")
        try:
            raw_results = qnode_to_run() 
        except Exception as e:
            raise RuntimeError(f"Error during PennyLane QNode execution: {e}") from e
        
        if self.shots > 0:
            if not isinstance(raw_results, pnp.ndarray):
                 return {"error": f"Expected samples (numpy array) from PennyLane QNode with shots, got {type(raw_results)}", "raw_result": str(raw_results)}

            if raw_results.ndim == 1: 
                if self.num_wires_for_circuit == 1:
                     samples_str = [str(int(s)) for s in raw_results]
                elif self.shots == 1 and raw_results.shape[0] == self.num_wires_for_circuit:
                     samples_str = ["".join(map(str,raw_results.astype(int)))]
                else:
                     return {"error": f"Received 1D samples array with shape {raw_results.shape} for {self.num_wires_for_circuit} wires and {self.shots} shots. Processing unclear.", "raw_result": str(raw_results)}
            elif raw_results.ndim == 2: 
                 if raw_results.shape[1] != self.num_wires_for_circuit: # Check if number of measured wires matches
                     return {"error": f"Sample array has {raw_results.shape[1]} wires, but circuit has {self.num_wires_for_circuit} wires. QASM measure ops might target a subset.", "raw_result": str(raw_results)}
                 samples_str = ["".join(map(str,row)) for row in raw_results.astype(int)]
            else:
                return {"error": f"Unexpected sample array dimensions: {raw_results.ndim}", "raw_result": str(raw_results)}

            counts = {}
            for s_val in samples_str:
                counts[s_val] = counts.get(s_val, 0) + 1
            return counts
        else:
            return {"info": "Analytic mode (shots=0 or None). Result is not processed into counts by this device.", "raw_result": raw_results}

    def monitor(self, res: Any) -> Dict[str, Any]:
        if isinstance(res, dict) and "counts" in res and isinstance(res["counts"], dict):
             internal_counts = res["counts"]
             total_shots_observed = sum(internal_counts.values())
             num_unique_outcomes = len(internal_counts)
             return {
                "total_shots_observed": int(total_shots_observed),
                "num_unique_outcomes": num_unique_outcomes,
                "counts": {str(k): int(v) for k,v in internal_counts.items()} 
            }
        elif isinstance(res, dict) and all(isinstance(k, str) and isinstance(v, (int, pnp.integer)) for k, v in res.items()):
            total_shots_observed = sum(res.values())
            num_unique_outcomes = len(res)
            cleaned_counts = {str(k): int(v) for k, v in res.items()}
            return {
                "total_shots_observed": int(total_shots_observed),
                "num_unique_outcomes": num_unique_outcomes,
                "counts": cleaned_counts 
            }
        return {"result_summary": f"Result not in expected counts format: {str(res)}"}
