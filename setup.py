# ~/haulvisor_project/setup.py
from setuptools import setup, find_packages
from pathlib import Path

setup(
    name="haulvisor",
    version="0.1.0",
    packages=find_packages(include=['haulvisor', 'haulvisor.*'], exclude=["docs", "tests*", "examples*"]),
    install_requires=[
        "pydantic>=2.7.0,<3.0.0",  # <--- CRITICAL CHANGE HERE: Requiring Pydantic V2
        "typer[all]>=0.12.0",     # Using a specific version for Typer for stability
        # --- Add your other direct dependencies here ---
        # e.g., "qiskit",
        # "amazon-braket-sdk", 
        # "qiskit-ibm-runtime",
        # "numpy",
        # "scipy",
    ],
    entry_points={
        "console_scripts": [
            "haulvisor = haulvisor.cli.cli:app",
        ],
    },
    python_requires=">=3.9",
    author="Xan",
    author_email="your.email@example.com", # Replace with your actual email
    description="Haulvisor: Quantum circuit management and execution platform.",
    long_description=(Path(__file__).parent / "README.md").read_text() if (Path(__file__).parent / "README.md").exists() else "",
    long_description_content_type="text/markdown",
    url="YOUR_PROJECT_URL_HERE", # e.g., your GitHub repository URL
    classifiers=[
        "Programming Language :: Python :: 3",
        # Consider removing "License :: OSI Approved :: MIT License" here
        # and adding a 'license_files' key or 'license' key with SPDX identifier
        # as per the deprecation warning if you want to modernize fully later.
        # For now, it's a warning, not an error.
        "Operating System :: OS Independent",
    ],
    # If you choose to use an SPDX identifier instead of classifier:
    # license="MIT", 
)
