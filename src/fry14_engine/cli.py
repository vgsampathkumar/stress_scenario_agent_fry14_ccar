"""Command-line entry point for the engine."""

from __future__ import annotations

from pathlib import Path

import typer

from fry14_engine import __version__
from fry14_engine.agent_demo import (
    DEFAULT_AGENT_DEMO_DB_PATH,
    format_agent_demo_report,
    run_agent_demo,
)
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


@app.command("agent-demo")
def agent_demo(
    count: int = typer.Option(20, help="Clean synthetic loan records to generate."),
    seed: int = typer.Option(7, help="Random seed, for reproducible demo runs."),
    db_path: Path = typer.Option(
        DEFAULT_AGENT_DEMO_DB_PATH, "--db-path", help="DuckDB file to run the agentic demo against."
    ),
) -> None:
    """Run all five agents (AG-1..AG-5) end-to-end through the real
    policy-enforced MCP tool server and checkpointed Agent Runtime — the
    CLI form of the "Agent UI" deliverable (see agent_demo.py's own
    docstring for why this is a documented CLI report, not a web UI, same
    as `fry14 demo` for Phase 0-7). Only the LLM itself is scripted
    (fixed, labeled illustrative responses) — no model credentials are
    wired into this repo."""
    result = run_agent_demo(db_path=db_path, count=count, seed=seed)
    typer.echo(format_agent_demo_report(result))


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
