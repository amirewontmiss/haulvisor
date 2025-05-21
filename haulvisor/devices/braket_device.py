# ~/haulvisor_project/haulvisor/devices/braket_device.py
"""
AWS Braket backend for HaulVisor
--------------------------------
* Uses the standard AWS credential chain (env vars first),
  so the AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY variables
  you configured on Render are picked up automatically.
* No AWS_PROFILE is ever set/required – that avoids the
  “profile not found (default)” error on cloud hosts.
"""

from __future__ import annotations

import os
import time
import pathlib
import yaml
import boto3
from botocore.exceptions import NoCredentialsError
from braket.aws import AwsSession, AwsDevice
from braket.ir.openqasm import Program
from .device import HaulDevice, register

# ── Config loading ────────────────────────────────────────────────────────── #
cfg_path = (
    pathlib.Path(__import__("haulvisor").__file__)
    .parent
    .joinpath("config", "default.yaml")
)
_br_cfg = yaml.safe_load(cfg_path.read_text()).get("braket", {})

DEVICE_ARN = _br_cfg.get(
    "device", "arn:aws:braket:::device/quantum-simulator/amazon/sv1"
)
SHOTS = int(_br_cfg.get("shots", 100))
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", _br_cfg.get("region", "us-east-1"))

# ── Device implementation ────────────────────────────────────────────────── #
@register
class BraketDevice(HaulDevice):
    name = "braket"
    max_qubits = 32

    # --------------------------------------------------------------------- #
    def compile(self, qasm: str) -> Program:
        """Clean up the QASM and wrap it in a Braket Program object."""
        cleaned_lines: list[str] = []
        for line in qasm.splitlines():
            s = line.strip()
            if s.startswith('include "qelib1.inc"'):
                continue                       # drop Qiskit include
            if s.startswith("cx "):
                line = line.replace("cx ", "cnot ", 1)
            cleaned_lines.append(line)
        return Program(source="\n".join(cleaned_lines) + "\n")

    # --------------------------------------------------------------------- #
    def run(self, program: Program):
        """
        Submit the task, poll until completion, and return measurement counts.
        Works with either a real QPU or a simulator ARN.
        """
        try:
            # Use env-var credentials (Render) or any default chain creds.
            boto_sess   = boto3.Session(region_name=AWS_REGION)
            aws_session = AwsSession(boto_session=boto_sess)
            device      = AwsDevice(DEVICE_ARN, aws_session=aws_session)
        except NoCredentialsError as exc:
            raise RuntimeError(
                "AWS credentials not found. Make sure AWS_ACCESS_KEY_ID, "
                "AWS_SECRET_ACCESS_KEY and AWS_DEFAULT_REGION are set."
            ) from exc

        task = device.run(program, shots=SHOTS)

        while (state := task.state()) not in ("COMPLETED", "FAILED", "CANCELLED"):
            time.sleep(5)

        if state != "COMPLETED":
            raise RuntimeError(f"Braket task {task.id} finished with state {state}")

        return task.result().measurement_counts

    # --------------------------------------------------------------------- #
    def monitor(self, counts):
        if isinstance(counts, dict):
            return {
                "shots": sum(counts.values()),
                "num_outcomes": len(counts),
                "counts": counts,
            }
        return {"result": str(counts)}

