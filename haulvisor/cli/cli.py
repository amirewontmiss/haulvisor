"""
haulvisor CLI – Quantum AI Hypervisor
-------------------------------------
"""

import typer
from ..api import core

app = typer.Typer(help="Haulvisor CLI – Quantum-AI Hypervisor")


@app.command()
def run(
    model: str,
    backend: str = typer.Option("pennylane", help="Backend name"),
    priority: str = typer.Option("normal", help="high|normal|low"),
    retries: int = typer.Option(3, help="Max backend retries on error"),
):
    """Compile, execute, and print the result."""
    res = core.run(
        model,
        backend,
        priority=priority,
        max_retries=retries,
    )
    typer.echo(res)


@app.command()
def dispatch(
    model: str,
    backend: str = typer.Option("pennylane", help="Backend name"),
    priority: str = typer.Option("normal", help="high|normal|low"),
    retries: int = typer.Option(3, help="Max backend retries on error"),
):
    """Queue a job and return its ID immediately."""
    job_id = core.dispatch(
        model,
        backend,
        priority=priority,
        max_retries=retries,
    )
    typer.echo(f"Job queued: {job_id}")


@app.command("logs")
def _logs(job: str):
    """Show the stored JSON log."""
    core.logs(job)


@app.command("devices")
def devices():
    """List available back-ends."""
    from ..devices import DEVICE_REGISTRY

    typer.echo(", ".join(DEVICE_REGISTRY))


@app.command("jobs")
def jobs(
    job_id: str = typer.Argument(None, help="Optional job UUID to inspect"),
    limit: int = typer.Option(20, help="Number of recent jobs to list"),
):
    """
    List recent jobs or show details of one specific job.
    """
    from .. import db
    from ..monitoring import logger

    if job_id:
        rec = db.fetch_job(job_id)
        if not rec:
            typer.echo("Job not found")
            raise typer.Exit(1)
        typer.echo(rec)
        logger.pretty(job_id)
    else:
        for r in db.list_jobs(limit):
            typer.echo(
                f"{r['id'][:8]}  {r['status']:<6}  {r['backend']:<9}  "
                f"{r['elapsed_ms'] or '-':>6} ms  {r['submitted']}"
            )


if __name__ == "__main__":
    app()

