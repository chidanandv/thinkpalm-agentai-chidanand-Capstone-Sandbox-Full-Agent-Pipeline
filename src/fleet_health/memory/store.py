from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fleet_health.config import settings
from fleet_health.models import Anomaly, FleetHealthReport


class MemoryStore:
    """SQLite-backed long-term memory for vessel baselines, anomaly history, and reports."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or settings.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vessel_baselines (
                    imo TEXT PRIMARY KEY,
                    vessel_name TEXT,
                    expected_me_mt_per_day REAL,
                    expected_at_speed_kn REAL,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS anomaly_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    imo TEXT NOT NULL,
                    anomaly_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    evidence_json TEXT,
                    recorded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    generated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_context (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def get_baseline(self, imo: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM vessel_baselines WHERE imo = ?", (imo,)
            ).fetchone()
        if not row:
            return None
        return dict(row)

    def upsert_baseline(
        self,
        imo: str,
        vessel_name: str,
        expected_me_mt_per_day: float,
        expected_at_speed_kn: float = 12.0,
    ) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO vessel_baselines (imo, vessel_name, expected_me_mt_per_day, expected_at_speed_kn, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(imo) DO UPDATE SET
                    vessel_name = excluded.vessel_name,
                    expected_me_mt_per_day = excluded.expected_me_mt_per_day,
                    expected_at_speed_kn = excluded.expected_at_speed_kn,
                    updated_at = excluded.updated_at
                """,
                (imo, vessel_name, expected_me_mt_per_day, expected_at_speed_kn, now),
            )

    def record_anomalies(self, anomalies: list[Anomaly]) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            for a in anomalies:
                conn.execute(
                    """
                    INSERT INTO anomaly_history (imo, anomaly_type, severity, message, evidence_json, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (a.vessel_imo, a.type, a.severity, a.message, json.dumps(a.evidence), now),
                )

    def get_recent_anomalies(self, imo: str, limit: int = 10) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM anomaly_history WHERE imo = ?
                ORDER BY recorded_at DESC LIMIT ?
                """,
                (imo, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def recurring_anomaly_notes(self, imo: str, anomaly_type: str, days: int = 30) -> str | None:
        history = self.get_recent_anomalies(imo, limit=20)
        matches = [h for h in history if h["anomaly_type"] == anomaly_type]
        if len(matches) >= 2:
            return (
                f"Recurring {anomaly_type} anomaly for IMO {imo} "
                f"({len(matches)} events in recent history)."
            )
        return None

    def save_report(self, report: FleetHealthReport) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reports (report_id, generated_at, payload_json)
                VALUES (?, ?, ?)
                """,
                (
                    report.report_id,
                    report.generated_at.isoformat(),
                    report.model_dump_json(),
                ),
            )

    def get_report(self, report_id: str) -> FleetHealthReport | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT payload_json FROM reports WHERE report_id = ?", (report_id,)
            ).fetchone()
        if not row:
            return None
        return FleetHealthReport.model_validate_json(row["payload_json"])

    def list_reports(self, limit: int = 20) -> list[dict[str, Any]]:
        """Recent saved reports (metadata only)."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT report_id, generated_at, payload_json
                FROM reports
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            anomalies = payload.get("anomalies") or []
            escalations = payload.get("escalations") or []
            out.append(
                {
                    "report_id": row["report_id"],
                    "generated_at": row["generated_at"],
                    "anomaly_count": len(anomalies),
                    "escalation_count": len(escalations),
                    "vessel_count": len(payload.get("vessel_summaries") or []),
                }
            )
        return out

    def set_session(self, key: str, value: Any) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO session_context (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), now),
            )

    def get_session(self, key: str) -> Any | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value_json FROM session_context WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        return json.loads(row["value_json"])
