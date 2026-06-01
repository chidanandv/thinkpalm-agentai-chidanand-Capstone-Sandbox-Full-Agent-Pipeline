"""Mock external tool — writes escalations to a JSON queue (shore-side ticketing stub)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fleet_health.models import Escalation


def notify_escalation_queue(escalation: Escalation, queue_dir: str = "./data/escalations") -> dict:
    path = Path(queue_dir)
    path.mkdir(parents=True, exist_ok=True)
    ticket_id = f"ESC-{escalation.vessel_imo}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    payload = {
        "ticket_id": ticket_id,
        "escalation": escalation.model_dump(mode="json"),
        "queued_at": datetime.utcnow().isoformat(),
        "status": "OPEN",
    }
    out_file = path / f"{ticket_id}.json"
    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return {"ticket_id": ticket_id, "path": str(out_file), "status": "queued"}
