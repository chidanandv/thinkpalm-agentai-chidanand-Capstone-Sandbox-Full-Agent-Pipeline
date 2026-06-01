from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from fleet_health.models import BunkerEntry, MaintenanceItem, NoonReport, PortCall


def _parse_date(value: str) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unparseable date: {value}")


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unparseable datetime: {value}")


def parse_noon_report(file_path: str | Path) -> list[NoonReport]:
    path = Path(file_path)
    reports: list[NoonReport] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            reports.append(
                NoonReport(
                    vessel_name=row["vessel_name"].strip(),
                    imo=row["imo"].strip(),
                    report_date=_parse_date(row["report_date"]),
                    lat=float(row["lat"]),
                    lon=float(row["lon"]),
                    speed_kn=float(row["speed_kn"]),
                    me_consumption_mt=float(row["me_consumption_mt"]),
                    ae_consumption_mt=float(row["ae_consumption_mt"]),
                    rob_hfo_mt=float(row["rob_hfo_mt"]),
                    rob_mgo_mt=float(row["rob_mgo_mt"]),
                    distance_nm=float(row["distance_nm"]),
                )
            )
    return reports


def parse_port_schedule(file_path: str | Path) -> list[PortCall]:
    path = Path(file_path)
    calls: list[PortCall] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            actual = row.get("actual_eta", "").strip()
            calls.append(
                PortCall(
                    imo=row["imo"].strip(),
                    port_name=row["port_name"].strip(),
                    planned_eta=_parse_datetime(row["planned_eta"]),
                    actual_eta=_parse_datetime(actual) if actual else None,
                    berth_window_end=_parse_datetime(row["berth_window_end"]),
                )
            )
    return calls


def parse_bunker_log(file_path: str | Path) -> list[BunkerEntry]:
    path = Path(file_path)
    entries: list[BunkerEntry] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(
                BunkerEntry(
                    imo=row["imo"].strip(),
                    log_date=_parse_date(row["log_date"]),
                    hfo_consumed_mt=float(row["hfo_consumed_mt"]),
                    mgo_consumed_mt=float(row["mgo_consumed_mt"]),
                    speed_kn=float(row["speed_kn"]),
                )
            )
    return entries


def parse_maintenance_alerts(file_path: str | Path) -> list[MaintenanceItem]:
    path = Path(file_path)
    items: list[MaintenanceItem] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            items.append(
                MaintenanceItem(
                    imo=row["imo"].strip(),
                    equipment=row["equipment"].strip(),
                    description=row["description"].strip(),
                    due_date=_parse_date(row["due_date"]),
                    status=row["status"].strip().lower(),  # type: ignore[arg-type]
                    severity=row["severity"].strip().lower(),  # type: ignore[arg-type]
                )
            )
    return items
