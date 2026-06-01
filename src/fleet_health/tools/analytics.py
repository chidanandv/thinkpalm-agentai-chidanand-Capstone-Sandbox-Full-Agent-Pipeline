from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fleet_health.config import settings
from fleet_health.models import (
    Anomaly,
    BunkerEntry,
    MaintenanceItem,
    NoonReport,
    PortCall,
    VesselSnapshot,
)


def compute_fuel_variance(
    snapshot: VesselSnapshot,
    baseline_me_mt_per_day: float,
    threshold_pct: float | None = None,
) -> dict[str, Any]:
    """Compare latest noon ME consumption against baseline."""
    threshold = threshold_pct or settings.fuel_variance_threshold_pct
    if not snapshot.noon:
        return {"status": "no_data", "variance_pct": None}

    actual = snapshot.noon.me_consumption_mt
    variance_pct = ((actual - baseline_me_mt_per_day) / baseline_me_mt_per_day) * 100
    over = variance_pct > threshold
    return {
        "status": "overconsumption" if over else "normal",
        "variance_pct": round(variance_pct, 2),
        "actual_mt": actual,
        "baseline_mt": baseline_me_mt_per_day,
        "threshold_pct": threshold,
        "speed_kn": snapshot.noon.speed_kn,
    }


def fuel_anomaly_from_variance(
    snapshot: VesselSnapshot, variance: dict[str, Any]
) -> Anomaly | None:
    if variance.get("status") != "overconsumption":
        return None
    pct = variance["variance_pct"]
    severity = "critical" if pct and pct > 15 else "high" if pct and pct > 10 else "medium"
    return Anomaly(
        vessel_imo=snapshot.imo,
        vessel_name=snapshot.vessel_name,
        type="fuel",
        severity=severity,
        message=(
            f"Fuel overconsumption: ME {variance['actual_mt']} MT/day vs baseline "
            f"{variance['baseline_mt']} MT/day ({pct}% variance)."
        ),
        evidence=variance,
    )


def check_schedule_slippage(
    port_calls: list[PortCall],
    slippage_hours: float | None = None,
) -> list[dict[str, Any]]:
    """Detect ETA vs berth window slippage."""
    limit = slippage_hours or settings.schedule_slippage_hours
    results: list[dict[str, Any]] = []
    for call in port_calls:
        eta = call.actual_eta or call.planned_eta
        delta_hours = (eta - call.berth_window_end).total_seconds() / 3600
        if delta_hours > limit:
            results.append(
                {
                    "imo": call.imo,
                    "port": call.port_name,
                    "slippage_hours": round(delta_hours, 1),
                    "planned_eta": call.planned_eta.isoformat(),
                    "effective_eta": eta.isoformat(),
                    "berth_window_end": call.berth_window_end.isoformat(),
                }
            )
    return results


def schedule_anomalies_from_slippage(
    snapshot: VesselSnapshot, slippages: list[dict[str, Any]]
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    for s in slippages:
        if s["imo"] != snapshot.imo:
            continue
        hours = s["slippage_hours"]
        severity = "critical" if hours > 48 else "high" if hours > 24 else "medium"
        anomalies.append(
            Anomaly(
                vessel_imo=snapshot.imo,
                vessel_name=snapshot.vessel_name,
                type="schedule",
                severity=severity,
                message=f"Schedule slippage at {s['port']}: {hours}h past berth window.",
                evidence=s,
            )
        )
    return anomalies


def check_pms_overdue(
    items: list[MaintenanceItem], as_of: date | None = None
) -> list[dict[str, Any]]:
    today = as_of or date.today()
    overdue: list[dict[str, Any]] = []
    for item in items:
        if item.status == "closed":
            continue
        if item.due_date < today:
            overdue.append(
                {
                    "imo": item.imo,
                    "equipment": item.equipment,
                    "description": item.description,
                    "due_date": item.due_date.isoformat(),
                    "days_overdue": (today - item.due_date).days,
                    "severity": item.severity,
                }
            )
    return overdue


def maintenance_anomalies_from_overdue(
    snapshot: VesselSnapshot, overdue: list[dict[str, Any]]
) -> list[Anomaly]:
    anomalies: list[Anomaly] = []
    for o in overdue:
        if o["imo"] != snapshot.imo:
            continue
        days = o["days_overdue"]
        base_sev = o["severity"]
        if base_sev == "critical" or days > 14:
            severity = "critical"
        elif days > 7 or base_sev == "high":
            severity = "high"
        else:
            severity = "medium"
        anomalies.append(
            Anomaly(
                vessel_imo=snapshot.imo,
                vessel_name=snapshot.vessel_name,
                type="maintenance",
                severity=severity,
                message=f"Overdue PMS: {o['equipment']} — {o['description']} ({days} days).",
                evidence=o,
            )
        )
    return anomalies


def bunker_trend_anomaly(
    snapshot: VesselSnapshot, entries: list[BunkerEntry], threshold_pct: float = 8.0
) -> Anomaly | None:
    vessel_entries = [e for e in entries if e.imo == snapshot.imo]
    if len(vessel_entries) < 2:
        return None
    vessel_entries.sort(key=lambda e: e.log_date)
    totals = [e.hfo_consumed_mt + e.mgo_consumed_mt for e in vessel_entries[-3:]]
    if len(totals) < 2:
        return None
    avg = sum(totals) / len(totals)
    latest = totals[-1]
    if avg == 0:
        return None
    variance = ((latest - avg) / avg) * 100
    if variance <= threshold_pct:
        return None
    return Anomaly(
        vessel_imo=snapshot.imo,
        vessel_name=snapshot.vessel_name,
        type="fuel",
        severity="medium",
        message=f"Bunker log trend: latest daily consumption {variance:.1f}% above 3-day average.",
        evidence={"variance_pct": round(variance, 2), "latest_mt": latest, "avg_mt": round(avg, 2)},
    )
