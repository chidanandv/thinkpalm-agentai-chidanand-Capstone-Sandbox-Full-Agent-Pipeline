#!/usr/bin/env python3
"""CLI for Fleet Health & Delivery Report pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from app.graph import run_pipeline
from app.memory.store import MemoryStore

app = typer.Typer(help="Fleet Health multi-agent pipeline CLI")


def _resolve_data_dir(data: Path) -> dict[str, str]:
    files = {
        "noon": data / "noon_reports.csv",
        "port_schedule": data / "port_schedule.csv",
        "bunker": data / "bunker_log.csv",
        "maintenance": data / "maintenance_alerts.csv",
    }
    missing = [k for k, p in files.items() if not p.is_file()]
    if missing:
        raise typer.BadParameter(f"Missing files in {data}: {', '.join(missing)}")
    return {k: str(v.resolve()) for k, v in files.items()}


@app.command()
def run(
    data: Path = typer.Option(
        Path("data/samples/fleet"),
        "--data",
        "-d",
        help="Directory containing noon, port, bunker, maintenance CSVs",
    ),
    imo: list[str] = typer.Option([], "--imo", help="Filter to specific IMO numbers"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write markdown report to file"),
    json_out: bool = typer.Option(False, "--json", help="Print full JSON report to stdout"),
) -> None:
    """Run the full LangGraph agent pipeline on sample or custom data."""
    paths = _resolve_data_dir(data)
    typer.echo(f"Running pipeline on: {data}")
    report = run_pipeline(paths, imo)
    typer.echo(f"Report ID: {report.report_id}")
    typer.echo(f"Anomalies: {len(report.anomalies)} | Escalations: {len(report.escalations)}")
    typer.echo(f"Tools invoked: {len(report.tool_trace)}")

    if output:
        output.write_text(report.markdown, encoding="utf-8")
        typer.echo(f"Markdown written to {output}")

    if json_out:
        typer.echo(report.model_dump_json(indent=2))
    else:
        typer.echo("\n--- Report preview ---\n")
        typer.echo(report.markdown[:2000])
        if len(report.markdown) > 2000:
            typer.echo("\n... (truncated; use --output for full report)")


@app.command()
def fetch(report_id: str) -> None:
    """Retrieve a previously generated report from SQLite memory."""
    report = MemoryStore().get_report(report_id)
    if not report:
        raise typer.Exit(code=1)
    typer.echo(report.model_dump_json(indent=2))


@app.command()
def memory(imo: str) -> None:
    """Show long-term memory for a vessel."""
    store = MemoryStore()
    typer.echo(json.dumps({"baseline": store.get_baseline(imo), "anomalies": store.get_recent_anomalies(imo)}, indent=2))


if __name__ == "__main__":
    app()
