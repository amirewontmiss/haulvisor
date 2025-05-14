"""
Haulvisor module entry point.

Usage
-----
$ python -m haulvisor <command> [options]

This simply forwards to the Typer-based CLI defined in `haulvisor/cli/cli.py`.
"""

from haulvisor.cli.cli import app as _cli_app


def main() -> None:
    """Run Haulvisor’s CLI."""
    _cli_app()


if __name__ == "__main__":
    main()

