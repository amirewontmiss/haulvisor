# ~/haulvisor_project/setup.py
from setuptools import setup, find_packages
from pathlib import Path

setup(
    name="haulvisor",
    version="0.1.0", # Or your current version
    # find_packages() will look in the current directory (where setup.py is)
    # and find the 'haulvisor' directory as a package because it has an __init__.py.
    # It will also find all sub-packages within it.
    packages=find_packages(include=['haulvisor', 'haulvisor.*'], exclude=["docs", "tests*", "examples*"]),
    # include=['haulvisor', 'haulvisor.*'] ensures it definitely picks up the main package and its submodules.
    install_requires=[
        "pydantic>=1.8.2,<2.0.0", # Pydantic V1/V2 conflict needs to be addressed later!
        "typer[all]>=0.12.0",     # Check Typer version if the 'all' warning persists or causes issues
        # --- Add your other direct dependencies here ---
        # "qiskit",
        # "amazon-braket-sdk", # or specific braket components like amazon-braket-schemas
        # "qiskit-ibm-runtime",
        # "numpy", # if used directly
        # "scipy", # if used directly
        # etc.
    ],
    entry_points={
        "console_scripts": [
            "haulvisor = haulvisor.cli.cli:app", # This path should be correct now
        ],
    },
    python_requires=">=3.9", # Or your actual Python version minimum
    author="Xan", # Your name/handle
    author_email="your.email@example.com", # Your email
    description="Haulvisor: Quantum circuit management and execution platform.",
    long_description=(Path(__file__).parent / "README.md").read_text() if (Path(__file__).parent / "README.md").exists() else "",
    long_description_content_type="text/markdown",
    url="URL_TO_YOUR_PROJECT_REPO", # e.g., GitHub link
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License", # Or your chosen license
        "Operating System :: OS Independent",
        # Add other relevant classifiers
    ],
)
