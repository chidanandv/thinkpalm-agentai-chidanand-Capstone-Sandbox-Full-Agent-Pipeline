from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from langgraph.graph import END, StateGraph

from fleet_health.agents.anomaly import anomaly_detection_node
from fleet_health.agents.escalation import escalation_node
from fleet_health.agents.ingest import ingest_node
from fleet_health.agents.summary import performance_summary_node
from fleet_health.memory.store import MemoryStore
from fleet_health.models import FleetHealthReport, PipelineState
from fleet_health.tools.export import render_report_markdown


def build_graph():
    """LangGraph pipeline: ingest → anomaly → summary → escalation → finalize."""
    graph = StateGraph(dict)

    graph.add_node("ingest", ingest_node)
    graph.add_node("anomaly", anomaly_detection_node)
    graph.add_node("summary", performance_summary_node)
    graph.add_node("escalation", escalation_node)
    graph.add_node("finalize", finalize_node)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "anomaly")
    graph.add_edge("anomaly", "summary")
    graph.add_edge("summary", "escalation")
    graph.add_edge("escalation", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
    pipeline = PipelineState.model_validate(state)
    report_id = pipeline.report_id or str(uuid.uuid4())
    markdown = render_report_markdown(pipeline, report_id)

    report = FleetHealthReport(
        report_id=report_id,
        generated_at=datetime.utcnow(),
        fleet_summary=pipeline.fleet_summary,
        vessel_summaries=pipeline.vessel_summaries,
        anomalies=pipeline.anomalies,
        escalations=pipeline.escalations,
        markdown=markdown,
        memory_notes=pipeline.memory_notes,
        tool_trace=pipeline.tool_trace,
    )
    MemoryStore().save_report(report)

    updated = pipeline.model_copy(
        update={"report_id": report_id, "markdown": markdown}
    )
    return updated.model_dump()


_compiled_graph = None


def run_pipeline(
    input_paths: dict[str, str],
    vessel_imos: list[str] | None = None,
    *,
    skip_llm: bool = False,
) -> FleetHealthReport:
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()

    initial = PipelineState(
        input_paths=input_paths,
        vessel_imos=vessel_imos or [],
        report_id=str(uuid.uuid4()),
        skip_llm=skip_llm,
    )
    final_state = _compiled_graph.invoke(initial.model_dump())
    pipeline = PipelineState.model_validate(final_state)

    return FleetHealthReport(
        report_id=pipeline.report_id,
        generated_at=datetime.utcnow(),
        fleet_summary=pipeline.fleet_summary,
        vessel_summaries=pipeline.vessel_summaries,
        anomalies=pipeline.anomalies,
        escalations=pipeline.escalations,
        markdown=pipeline.markdown,
        memory_notes=pipeline.memory_notes,
        tool_trace=pipeline.tool_trace,
    )
