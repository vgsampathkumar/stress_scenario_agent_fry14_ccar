"""Command-line entry point for the engine."""

from __future__ import annotations

from pathlib import Path

import typer

from fry14_engine import __version__
from fry14_engine.contracts.data_dictionary import generate_data_dictionary
from fry14_engine.contracts.registry import ContractRegistry
from fry14_engine.db import REPO_ROOT
from fry14_engine.demo import DEFAULT_DEMO_DB_PATH, format_report, run_demo

app = typer.Typer(help="Governed Agentic Data Product Orchestrator (FR Y-14 / CCAR)")


@app.command()
def version() -> None:
    """Print the engine version."""
    typer.echo(__version__)


@app.command()
def demo(
    count: int = typer.Option(60, help="Total synthetic loan records to generate."),
    bad_rate: float = typer.Option(
        0.2, "--bad-rate", help="Fraction of records deliberately seeded with a contract violation."
    ),
    seed: int = typer.Option(42, help="Random seed, for reproducible demo runs."),
    db_path: Path = typer.Option(
        DEFAULT_DEMO_DB_PATH, "--db-path", help="DuckDB file to ingest/validate into."
    ),
) -> None:
    """Run the pipeline as built so far: generate synthetic loans, ingest
    them via the batch-file and event-stream adapters, validate them
    against the active contract, and print a report. Every step here is the
    real engine code - nothing is mocked for this command."""
    result = run_demo(count=count, bad_record_rate=bad_rate, seed=seed, db_path=db_path)
    typer.echo(format_report(result))


@app.command("data-dictionary")
def data_dictionary(
    contract_id: str = typer.Option("commercial_loan", help="Contract to document."),
) -> None:
    """Print a Markdown data dictionary generated directly from the active
    contract's field definitions — never hand-maintained, so it can't
    drift from what's actually enforced."""
    registry = ContractRegistry(REPO_ROOT / "config" / "contracts")
    contract = registry.get_active(contract_id)
    typer.echo(generate_data_dictionary(contract))


if __name__ == "__main__":
    app()
