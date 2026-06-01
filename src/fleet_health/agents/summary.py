from __future__ import annotations

import json
from typing import Any

from fleet_health.llm import claude_json, is_llm_enabled
from fleet_health.models import PipelineState


def performance_summary_node(state: dict[str, Any]) -> dict[str, Any]:
    """Agent 3: Draft fleet superintendent performance summary via Claude."""
    pipeline = PipelineState.model_validate(state)

    payload = {
        "vessels": [
            {
                "imo": s.imo,
                "name": s.vessel_name,
                "noon": s.noon.model_dump(mode="json") if s.noon else None,
                "port_calls": len(s.port_calls),
                "open_maintenance": sum(1 for m in s.maintenance if m.status != "closed"),
            }
            for s in pipeline.snapshots
        ],
        "anomalies": [a.model_dump(mode="json") for a in pipeline.anomalies],
        "memory_notes": pipeline.memory_notes,
    }

    if not is_llm_enabled(skip_llm=pipeline.skip_llm):
        fleet_summary = _fallback_fleet_summary(pipeline, "LLM disabled (fast mode)")
        vessel_summaries = _fallback_vessel_summaries(pipeline)
    else:
        try:
            result = claude_json(
                system=(
                    "You are a maritime fleet superintendent assistant. "
                    "Write concise operational summaries for ship management executives. "
                    "Return JSON: {"
                    '"fleet_summary": "2-4 paragraph executive summary", '
                    '"vessel_summaries": [{"imo": "...", "vessel_name": "...", "summary": "..."}]'
                    "}"
                ),
                user=json.dumps(payload, indent=2, default=str),
            )
            fleet_summary = result.get("fleet_summary", "")
            vessel_summaries = result.get("vessel_summaries", [])
        except (ValueError, json.JSONDecodeError, Exception) as exc:
            fleet_summary = _fallback_fleet_summary(pipeline, str(exc))
            vessel_summaries = _fallback_vessel_summaries(pipeline)

    tool_trace = list(pipeline.tool_trace)
    tool_trace.append(
        {"tool": "claude_performance_summary", "result_summary": "fleet narrative drafted"}
    )

    updated = pipeline.model_copy(
        update={
            "fleet_summary": fleet_summary,
            "vessel_summaries": vessel_summaries,
            "tool_trace": tool_trace,
        }
    )
    return updated.model_dump()


def _fallback_fleet_summary(pipeline: PipelineState, reason: str) -> str:
    n_crit = sum(1 for a in pipeline.anomalies if a.severity == "critical")
    return (
        f"Fleet review covering {len(pipeline.snapshots)} vessel(s). "
        f"{len(pipeline.anomalies)} anomaly(ies) detected ({n_crit} critical). "
        f"(LLM summary unavailable: {reason})"
    )


def _fallback_vessel_summaries(pipeline: PipelineState) -> list[dict[str, Any]]:
    summaries = []
    for s in pipeline.snapshots:
        vessel_anomalies = [a for a in pipeline.anomalies if a.vessel_imo == s.imo]
        summaries.append(
            {
                "imo": s.imo,
                "vessel_name": s.vessel_name,
                "summary": (
                    f"{len(vessel_anomalies)} anomaly(ies) on record. "
                    f"Latest speed {s.noon.speed_kn if s.noon else 'N/A'} kn."
                ),
            }
        )
    return summaries
