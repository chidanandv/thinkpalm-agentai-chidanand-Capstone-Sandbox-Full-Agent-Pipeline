from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from fleet_health.llm import claude_json, is_llm_enabled
from fleet_health.models import Escalation, PipelineState
from fleet_health.tools.escalation_queue import notify_escalation_queue

CRITICAL_KEYWORDS = (
    "main engine",
    "steering",
    "blackout",
    "pollution",
    "cargo pump",
    "boiler explosion",
)


def escalation_node(state: dict[str, Any]) -> dict[str, Any]:
    """Agent 4: Flag critical defects for shore-side escalation."""
    pipeline = PipelineState.model_validate(state)
    rule_based = _rule_based_escalations(pipeline)

    llm_escalations: list[Escalation] = []
    if is_llm_enabled(skip_llm=pipeline.skip_llm):
        try:
            llm_escalations = _llm_escalations(pipeline, rule_based)
        except Exception:
            llm_escalations = []

    seen = set()
    escalations: list[Escalation] = []
    for esc in rule_based + llm_escalations:
        key = (esc.vessel_imo, esc.title)
        if key not in seen:
            seen.add(key)
            escalations.append(esc)

    tool_trace = list(pipeline.tool_trace)
    for esc in escalations:
        if esc.severity == "critical":
            ticket = notify_escalation_queue(esc)
            tool_trace.append(
                {
                    "tool": "notify_escalation_queue",
                    "result_summary": f"ticket {ticket['ticket_id']}",
                }
            )

    tool_trace.append(
        {
            "tool": "claude_escalation_review",
            "result_summary": f"{len(escalations)} escalations",
        }
    )

    updated = pipeline.model_copy(
        update={"escalations": escalations, "tool_trace": tool_trace}
    )
    return updated.model_dump()


def _rule_based_escalations(pipeline: PipelineState) -> list[Escalation]:
    escalations: list[Escalation] = []
    deadline = date.today() + timedelta(days=3)

    for anomaly in pipeline.anomalies:
        if anomaly.severity not in ("critical", "high"):
            continue
        escalations.append(
            Escalation(
                vessel_imo=anomaly.vessel_imo,
                vessel_name=anomaly.vessel_name,
                title=f"{anomaly.type.title()} — {anomaly.severity.upper()}",
                severity="critical" if anomaly.severity == "critical" else "high",
                owner="Fleet Superintendent Office",
                deadline=deadline,
                rationale=anomaly.message,
                evidence_refs=[f"anomaly:{anomaly.type}:{anomaly.vessel_imo}"],
            )
        )

    for snapshot in pipeline.snapshots:
        for item in snapshot.maintenance:
            if item.status == "closed":
                continue
            text = f"{item.equipment} {item.description}".lower()
            is_critical = item.severity == "critical" or any(k in text for k in CRITICAL_KEYWORDS)
            if not is_critical:
                continue
            days_over = (date.today() - item.due_date).days
            escalations.append(
                Escalation(
                    vessel_imo=snapshot.imo,
                    vessel_name=snapshot.vessel_name,
                    title=f"Critical defect: {item.equipment}",
                    severity="critical",
                    owner="Technical Superintendent / DPA",
                    deadline=date.today() + timedelta(days=1 if days_over > 7 else 3),
                    rationale=item.description,
                    evidence_refs=[f"maintenance:{item.equipment}"],
                )
            )

    return escalations


def _llm_escalations(
    pipeline: PipelineState, existing: list[Escalation]
) -> list[Escalation]:
    payload = {
        "anomalies": [a.model_dump(mode="json") for a in pipeline.anomalies],
        "existing_escalations": [e.model_dump(mode="json") for e in existing],
        "maintenance": [
            m.model_dump(mode="json")
            for s in pipeline.snapshots
            for m in s.maintenance
            if m.status != "closed"
        ],
    }
    result = claude_json(
        system=(
            "You are a maritime technical superintendent. Identify items requiring "
            "shore-side escalation only. Return JSON: "
            '{"escalations": [{"vessel_imo","vessel_name","title","severity":"high|critical",'
            '"owner","deadline":"YYYY-MM-DD","rationale","evidence_refs":[]}]}'
        ),
        user=json.dumps(payload, indent=2, default=str),
    )
    out: list[Escalation] = []
    for raw in result.get("escalations", []):
        if raw.get("vessel_imo") in {e.vessel_imo for e in existing} and not raw.get("title"):
            continue
        out.append(Escalation.model_validate(raw))
    return out
