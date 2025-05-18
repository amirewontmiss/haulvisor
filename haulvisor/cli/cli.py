"""
Haulvisor CLI – Quantum AI Hypervisor
-------------------------------------
"""

import typer
from typing_extensions import Annotated
from typing import Optional 
from pathlib import Path
import json 
import inspect # To get docstrings

# Relative imports for Haulvisor's internal modules
from ..api import core
from ..devices import DEVICE_REGISTRY 
from .. import db as haulvisor_db 
from ..monitoring import logger as haulvisor_logger 
from ..scheduler import qpu_router 

# Main Typer application instance
app = typer.Typer(
    name="haulvisor",
    help="Haulvisor CLI – Quantum-AI Hypervisor. A unified interface for quantum circuit execution.",
    add_completion=True, 
    no_args_is_help=True 
)

# --- Commands ---

@app.command(name="run", help="Compile, execute, and print the result of a quantum circuit model.")
def run(
    model: Annotated[Path, typer.Argument(
        help="Path to the JSON circuit model file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True 
    )],
    backend: Annotated[str, typer.Option(help="Backend name (e.g., pennylane, qiskit).")] = "pennylane",
    priority: Annotated[str, typer.Option(help="Job priority: high|normal|low.")] = "normal",
    retries: Annotated[int, typer.Option(help="Max backend retries on transient error.")] = 3,
    monitor: Annotated[bool, typer.Option(help="Display logs after completion.")] = True,
):
    """
    Compile, execute a quantum circuit model, and print the result.
    This command runs the full pipeline synchronously.

    The final result of the quantum computation (e.g., statevector, counts)
    is printed to standard output.

    Examples:
      # Run on local PennyLane simulator (default backend)
      haulvisor run examples/ghz.json

      # Run on Qiskit simulator and save output to a file
      haulvisor run examples/quantum_vqe.json --backend qiskit > noiseless_qiskit.vec

      # Run with high priority
      haulvisor run examples/teleportation.json --backend braket --priority high
    """
    try:
        result = core.run(
            model_path=model,
            backend=backend,
            priority=priority,
            max_retries=retries,
            monitor=monitor 
        )
        if result is not None:
            if isinstance(result, Exception): 
                typer.secho(f"Job failed with error: {result}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=1)
            else:
                if hasattr(result, '__str__') and not isinstance(result, (list, dict)): 
                    typer.echo(str(result))
                else: 
                    try:
                        typer.echo(json.dumps(result, indent=2) if isinstance(result, (dict, list)) else repr(result))
                    except TypeError: 
                         typer.echo(repr(result))
    except FileNotFoundError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except ValueError as e: 
        typer.secho(f"Configuration or Value Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.secho(f"An unexpected error occurred in 'run': {type(e).__name__} - {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

@app.command(name="dispatch", help="Compile and queue a job for asynchronous execution, returning its ID immediately.")
def dispatch(
    model: Annotated[Path, typer.Argument(
        help="Path to the JSON circuit model file.",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True
    )],
    backend: Annotated[str, typer.Option(help="Backend name (e.g., pennylane, qiskit).")] = "pennylane",
    priority: Annotated[str, typer.Option(help="Job priority: high|normal|low.")] = "normal",
    retries: Annotated[int, typer.Option(help="Max backend retries on transient error.")] = 3,
):
    """
    Compile a quantum circuit model and dispatch it to the job queue.
    Returns the job ID immediately for later status checks using 'haulvisor jobs <ID>' or 'haulvisor logs <ID>'.

    Examples:
      # Dispatch a job to the default PennyLane backend
      haulvisor dispatch examples/grover.json

      # Dispatch to IBM Quantum backend with low priority
      haulvisor dispatch examples/qft.json --backend ibm --priority low
    """
    try:
        job_id = core.dispatch(
            model_path=model, 
            backend=backend,
            priority=priority,
            max_retries=retries
        )
        typer.echo(f"Job dispatched. ID: {typer.style(job_id, fg=typer.colors.GREEN)}")
    except FileNotFoundError as e:
        typer.secho(f"Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except ValueError as e:
        typer.secho(f"Configuration or Value Error: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.secho(f"An unexpected error occurred during dispatch: {type(e).__name__} - {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

@app.command("logs", help="Show the stored JSON log for a specific job ID.")
def show_logs( # Renamed from _logs to avoid leading underscore if not intended as private
    job_id: Annotated[str, typer.Argument(help="The ID of the job to show logs for.")]
):
    """
    Retrieve and display the JSON log for a previously submitted job.
    The log contains submission details, circuit, metrics, and completion status.
    """
    try:
        core.logs(job_id) 
    except FileNotFoundError: 
        typer.secho(f"Error: Log file for job ID '{job_id}' not found.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.secho(f"An error occurred while retrieving logs for job '{job_id}': {type(e).__name__} - {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)

@app.command("devices", help="List all available quantum back-ends (simulators and hardware).")
def list_devices():
    """
    Displays a list of quantum back-ends that Haulvisor can interface with.
    This list is typically derived from the configured device plugins.
    """
    typer.echo("Available back-ends (from DEVICE_REGISTRY):")
    if DEVICE_REGISTRY: 
        for device_name in sorted(list(DEVICE_REGISTRY)): # Sort for consistent order
            typer.echo(f"  - {device_name}")
    else:
        typer.echo(typer.style("  No back-ends found in DEVICE_REGISTRY.", fg=typer.colors.YELLOW))

@app.command("jobs", help="List recent jobs or show detailed information for a specific job ID.")
def list_or_show_jobs( 
    job_id: Annotated[Optional[str], typer.Argument(help="Specific job ID to show details for. If omitted, lists recent jobs.")] = None,
    limit: Annotated[int, typer.Option(help="Number of recent jobs to list.")] = 10
):
    """
    Manages and displays information about past and current jobs from the database.
    - If JOB_ID is provided, shows detailed information for that job.
    - If JOB_ID is omitted, lists the most recent jobs.
    """
    if job_id:
        typer.echo(f"Fetching details for job ID: {job_id}")
        job_detail = haulvisor_db.get_job_by_id(job_id) 
        if job_detail:
            typer.echo(json.dumps(job_detail, indent=2)) 
        else:
            typer.secho(f"Job ID '{job_id}' not found in database.", fg=typer.colors.RED)
            raise typer.Exit(code=1)
    else:
        typer.echo(f"Listing last {limit} jobs:")
        recent_jobs = haulvisor_db.list_jobs(limit=limit)
        if recent_jobs:
            for r in recent_jobs:
                status_color = typer.colors.GREEN if r.get('status') == 'completed' else \
                               typer.colors.YELLOW if r.get('status') in ['queued', 'running', 'submitted'] else \
                               typer.colors.RED
                elapsed = r.get('elapsed_ms', '-')
                if elapsed is None: elapsed = '-' 
                
                typer.echo(
                    f"  ID: {r.get('id', 'N/A')[:8]:<8} | "
                    f"Status: {typer.style(str(r.get('status', 'N/A')), fg=status_color):<15} | " 
                    f"Backend: {r.get('backend', 'N/A'):<10} | "
                    f"Time: {str(elapsed):>6} ms | " # Ensure elapsed is string for formatting
                    f"Submitted: {r.get('submitted', 'N/A')}"
                )
        else:
            typer.echo("No jobs found in the database.")

@app.command(name="commands", help="List all available Haulvisor commands with descriptions and examples.")
def list_all_commands():
    """
    Provides a detailed list of all available Haulvisor commands,
    their primary functions, and usage examples where available.
    """
    typer.echo(typer.style("Available Haulvisor Commands:", fg=typer.colors.BRIGHT_BLUE, bold=True))
    
    relevant_commands_info = [
        cmd_info for cmd_info in app.registered_commands 
        if cmd_info.callback and cmd_info.name not in ["commands"] # Exclude self
    ]
    sorted_commands_info = sorted(relevant_commands_info, key=lambda cmd_info: cmd_info.name or "")

    if not sorted_commands_info:
        typer.echo("No user-defined commands registered.")
        return

    for cmd_info in sorted_commands_info:
        cmd_name = cmd_info.name
        cmd_help = cmd_info.help or "No description provided." # From @app.command(help=...)
        
        typer.echo(f"\n  {typer.style(str(cmd_name), fg=typer.colors.GREEN, bold=True)}")
        typer.echo(f"    {cmd_help}")

        # Extract and print examples from the command's docstring
        if cmd_info.callback and cmd_info.callback.__doc__:
            docstring = inspect.getdoc(cmd_info.callback) # Cleans up indentation
            if docstring:
                lines = docstring.splitlines()
                in_examples_section = False
                example_lines = []
                for line in lines:
                    stripped_line = line.strip()
                    if stripped_line.lower().startswith("examples:"):
                        in_examples_section = True
                        # Optionally print a header for examples, or let the first example line do it
                        # typer.echo(typer.style("    Examples:", bold=True)) 
                        continue # Skip the "Examples:" line itself
                    if in_examples_section:
                        if stripped_line == "" and any(example_lines) and not example_lines[-1].strip() == "":
                            # Stop if an empty line is found after some example lines,
                            # unless the previous line was also empty (allows for multi-line examples with breaks)
                            # Or, more simply, stop if the line is not indented (assuming examples are indented)
                            if not line.startswith("  "): # Heuristic: examples are indented
                                break 
                        example_lines.append(line) # Keep original indentation for display
                
                if example_lines:
                    typer.echo(typer.style("    Examples:", underline=True))
                    for ex_line in example_lines:
                        # Print example lines, maintaining their original relative indentation
                        # but ensuring they are printed under the "Examples:" section.
                        typer.echo(f"      {ex_line.strip()}") # Standard indent for examples

        typer.echo(f"    (For full options: haulvisor {cmd_name} --help)")
        
    typer.echo(f"\nFor general help, type: {typer.style('haulvisor --help', bold=True)}")

@app.callback()
def main_callback(ctx: typer.Context):
    """
    Haulvisor CLI: Manage and execute quantum circuits across various backends.
    """
    # The db.init() is called when db.py is imported.
    pass

if __name__ == "__main__":
    app()

