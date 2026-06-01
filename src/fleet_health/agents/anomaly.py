from __future__ import annotations

from typing import Any

from fleet_health.config import settings
from fleet_health.memory.store import MemoryStore
from fleet_health.models import Anomaly, PipelineState
from fleet_health.tools.analytics import (
    bunker_trend_anomaly,
    check_pms_overdue,
    check_schedule_slippage,
    compute_fuel_variance,
    fuel_anomaly_from_variance,
    maintenance_anomalies_from_overdue,
    schedule_anomalies_from_slippage,
)

DEFAULT_BASELINES: dict[str, float] = {
    "9123456": 22.0,
    "9234567": 24.5,
    "9345678": 26.0,
}


def anomaly_detection_node(state: dict[str, Any]) -> dict[str, Any]:
    """Agent 2: Detect fuel, schedule, and maintenance anomalies using custom tools."""
    pipeline = PipelineState.model_validate(state)
    memory = MemoryStore()
    tool_trace = list(pipeline.tool_trace)
    all_anomalies: list[Anomaly] = []
    memory_notes: list[str] = list(pipeline.memory_notes)

    all_port_calls = [pc for s in pipeline.snapshots for pc in s.port_calls]
    slippages = check_schedule_slippage(all_port_calls)
    tool_trace.append(
        {
            "tool": "check_schedule_slippage",
            "result_summary": f"{len(slippages)} slippage events",
        }
    )

    all_maintenance = [m for s in pipeline.snapshots for m in s.maintenance]
    overdue = check_pms_overdue(all_maintenance)
    tool_trace.append(
        {"tool": "check_pms_overdue", "result_summary": f"{len(overdue)} overdue items"}
    )

    for snapshot in pipeline.snapshots:
        baseline_row = memory.get_baseline(snapshot.imo)
        baseline_mt = (
            baseline_row["expected_me_mt_per_day"]
            if baseline_row
            else DEFAULT_BASELINES.get(snapshot.imo, 24.0)
        )

        variance = compute_fuel_variance(
            snapshot,
            baseline_mt,
            settings.fuel_variance_threshold_pct,
        )
        tool_trace.append(
            {
                "tool": "compute_fuel_variance",
                "result_summary": f"IMO {snapshot.imo}: {variance.get('status')} ({variance.get('variance_pct')}%)",
            }
        )

        fuel_anomaly = fuel_anomaly_from_variance(snapshot, variance)
        if fuel_anomaly:
            all_anomalies.append(fuel_anomaly)
            note = memory.recurring_anomaly_notes(snapshot.imo, "fuel")
            if note:
                memory_notes.append(note)

        trend = bunker_trend_anomaly(snapshot, snapshot.bunker_entries)
        if trend:
            all_anomalies.append(trend)

        all_anomalies.extend(schedule_anomalies_from_slippage(snapshot, slippages))
        all_anomalies.extend(maintenance_anomalies_from_overdue(snapshot, overdue))

        for anomaly_type in ("fuel", "schedule", "maintenance"):
            note = memory.recurring_anomaly_notes(snapshot.imo, anomaly_type)
            if note and note not in memory_notes:
                memory_notes.append(note)

    memory.record_anomalies(all_anomalies)

    updated = pipeline.model_copy(
        update={
            "anomalies": all_anomalies,
            "tool_trace": tool_trace,
            "memory_notes": memory_notes,
        }
    )
    return updated.model_dump()
