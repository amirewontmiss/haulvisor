"""
haulvisor.devices.braket_device
--------------------------------
AWS Braket backend for Haulvisor.

Submits OpenQASM circuits via Braket’s Program IR, polls to completion,
and returns measurement counts.
"""

import os
import time
import pathlib
import yaml

from botocore.exceptions import ProfileNotFound
from braket.aws import AwsDevice
from braket.ir.openqasm import Program
from .device import HaulDevice, register

# ── Load config ───────────────────────────────────────────────────────────── #
cfg_path = (
    pathlib.Path(__import__("haulvisor").__file__)
    .parent
    .joinpath("config", "default.yaml")
)
_br_cfg = yaml.safe_load(cfg_path.read_text()).get("braket", {})

# Only set AWS_PROFILE / AWS_REGION if you explicitly provided them,
# otherwise let the standard AWS chain operate.
if "profile" in _br_cfg:
    os.environ["AWS_PROFILE"] = _br_cfg["profile"]
if "region" in _br_cfg:
    os.environ["AWS_REGION"] = _br_cfg["region"]

DEVICE_ARN = _br_cfg.get(
    "device", "arn:aws:braket:::device/quantum-simulator/amazon/sv1"
)
SHOTS = int(_br_cfg.get("shots", 100))


@register
class BraketDevice(HaulDevice):
    name = "braket"
    max_qubits = 32

    def compile(self, qasm: str) -> Program:
        """
        Wrap the OpenQASM string into a Braket Program.
        - Strip out any `include "qelib1.inc";` lines.
        - Rename `cx` → `cnot` for Braket compatibility.
        """
        cleaned = []
        for line in qasm.splitlines():
            stripped = line.strip()
            # drop Qiskit include directive
            if stripped.startswith('include "qelib1.inc"'):
              continue
            # rename cx to cnot
            if stripped.startswith("cx "):
                # e.g. "cx q[0], q[1];" → "cnot q[0], q[1];"
                line = line.replace("cx ", "cnot ")
            cleaned.append(line)
        cleaned_qasm = "\n".join(cleaned) + "\n"

        return Program(source=cleaned_qasm)


    def run(self, program: Program):
        """
        Submit the Program to AWS Braket, poll until done, and return counts.
        """
        try:
            aws_dev = AwsDevice(DEVICE_ARN)
        except ProfileNotFound as e:
            raise RuntimeError(
                f"AWS profile not found ({os.environ.get('AWS_PROFILE')}). "
                "Please configure your AWS credentials (~/.aws/credentials) "
                "or set AWS_PROFILE / AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY."
            ) from e

        task = aws_dev.run(program, shots=SHOTS)

        while (state := task.state()) not in ("COMPLETED", "FAILED", "CANCELLED"):
            time.sleep(5)

        if state != "COMPLETED":
            raise RuntimeError(f"Braket job {task.id} ended with state {state}")

        return task.result().measurement_counts

    def monitor(self, res):
        if isinstance(res, dict):
            total = sum(res.values())
            return {"shots": total, "counts": res}
        return {"result": str(res)}

