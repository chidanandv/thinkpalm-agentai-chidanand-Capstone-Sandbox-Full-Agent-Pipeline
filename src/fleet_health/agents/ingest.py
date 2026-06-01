from __future__ import annotations

from pathlib import Path
from typing import Any

from fleet_health.memory.store import MemoryStore
from fleet_health.models import PipelineState, VesselSnapshot
from fleet_health.tools.parsers import (
    parse_bunker_log,
    parse_maintenance_alerts,
    parse_noon_report,
    parse_port_schedule,
)

# Default baselines when DB is empty (MT ME per day at ~12 kn)
DEFAULT_BASELINES: dict[str, tuple[str, float]] = {
    "9123456": ("MV Pacific Star", 22.0),
    "9234567": ("MV Atlantic Runner", 24.5),
    "9345678": ("MV Nordic Spirit", 26.0),
}


def ingest_node(state: dict[str, Any]) -> dict[str, Any]:
    """Agent 1: Parse and normalise voyage, port, bunker, and maintenance data."""
    pipeline = PipelineState.model_validate(state)
    memory = MemoryStore()
    paths = pipeline.input_paths

    tool_trace = list(pipeline.tool_trace)
    noon_reports = []
    port_calls = []
    bunker_entries = []
    maintenance = []

    if "noon" in paths:
        noon_reports = parse_noon_report(paths["noon"])
        tool_trace.append(
            {"tool": "parse_noon_report", "result_summary": f"{len(noon_reports)} reports"}
        )
    if "port_schedule" in paths:
        port_calls = parse_port_schedule(paths["port_schedule"])
        tool_trace.append(
            {"tool": "parse_port_schedule", "result_summary": f"{len(port_calls)} port calls"}
        )
    if "bunker" in paths:
        bunker_entries = parse_bunker_log(paths["bunker"])
        tool_trace.append(
            {"tool": "parse_bunker_log", "result_summary": f"{len(bunker_entries)} entries"}
        )
    if "maintenance" in paths:
        maintenance = parse_maintenance_alerts(paths["maintenance"])
        tool_trace.append(
            {
                "tool": "parse_maintenance_alerts",
                "result_summary": f"{len(maintenance)} items",
            }
        )

    imos = set(pipeline.vessel_imos)
    for r in noon_reports:
        imos.add(r.imo)
    for c in port_calls:
        imos.add(c.imo)
    for b in bunker_entries:
        imos.add(b.imo)
    for m in maintenance:
        imos.add(m.imo)

    snapshots: list[VesselSnapshot] = []
    for imo in sorted(imos):
        vessel_noons = [r for r in noon_reports if r.imo == imo]
        latest_noon = max(vessel_noons, key=lambda r: r.report_date) if vessel_noons else None
        name = latest_noon.vessel_name if latest_noon else _name_for_imo(imo)

        if latest_noon:
            baseline_mt = DEFAULT_BASELINES.get(imo, (name, 24.0))[1]
            memory.upsert_baseline(imo, name, baseline_mt)

        snapshots.append(
            VesselSnapshot(
                imo=imo,
                vessel_name=name,
                noon=latest_noon,
                port_calls=[c for c in port_calls if c.imo == imo],
                bunker_entries=[b for b in bunker_entries if b.imo == imo],
                maintenance=[m for m in maintenance if m.imo == imo],
            )
        )

    memory.set_session("last_ingest_paths", {k: str(Path(v).resolve()) for k, v in paths.items()})

    if pipeline.vessel_imos:
        allowed = set(pipeline.vessel_imos)
        snapshots = [s for s in snapshots if s.imo in allowed]
        imos = allowed & {s.imo for s in snapshots}

    updated = pipeline.model_copy(
        update={
            "snapshots": snapshots,
            "vessel_imos": sorted(imos),
            "tool_trace": tool_trace,
        }
    )
    return updated.model_dump()


def _name_for_imo(imo: str) -> str:
    return DEFAULT_BASELINES.get(imo, (f"Vessel {imo}", 24.0))[0]
