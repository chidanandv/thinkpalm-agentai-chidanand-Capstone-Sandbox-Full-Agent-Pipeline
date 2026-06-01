from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fleet_health.graph import run_pipeline
from fleet_health.memory.store import MemoryStore
from fleet_health.models import FleetHealthReport

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "static"
SAMPLES_DIR = ROOT / "data" / "samples"
_pipeline_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pipeline")
logger = logging.getLogger("fleet_health")


def _norm_path(path: Path) -> str:
    """Forward-slash paths for stable JSON in the browser."""
    return path.resolve().as_posix()


async def _run_pipeline_async(
    paths: dict[str, str],
    vessel_imos: list[str],
    *,
    skip_llm: bool,
) -> FleetHealthReport:
    """Run sync pipeline off the event loop so the server stays responsive."""
    mode = "fast" if skip_llm else "full"
    logger.info("Pipeline start (%s, %s vessel filter(s))", mode, len(vessel_imos))
    started = time.perf_counter()
    loop = asyncio.get_running_loop()
    try:
        report = await loop.run_in_executor(
            _pipeline_pool,
            partial(run_pipeline, paths, vessel_imos, skip_llm=skip_llm),
        )
    except Exception:
        logger.exception("Pipeline failed after %.1fs", time.perf_counter() - started)
        raise
    logger.info(
        "Pipeline done in %.1fs — report %s (%s anomalies)",
        time.perf_counter() - started,
        report.report_id[:8],
        len(report.anomalies),
    )
    return report


app = FastAPI(
    title="Fleet Health & Delivery Report API",
    description="Multi-agent maritime pipeline (LangGraph + Claude + SQLite)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateFromPathsRequest(BaseModel):
    noon_path: str
    port_schedule_path: str
    bunker_path: str
    maintenance_path: str
    vessel_imos: list[str] = Field(default_factory=list)
    fast: bool = True


def _dashboard_index() -> Path:
    return STATIC_DIR / "index.html"


@app.get("/")
def serve_dashboard() -> FileResponse:
    """Fleet Health operations dashboard."""
    index = _dashboard_index()
    if not index.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Dashboard UI not found at {index}. Restart uvicorn from the project root.",
        )
    return FileResponse(
        index,
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/index.html")
def serve_dashboard_alias() -> FileResponse:
    """Alias for bookmarked /index.html URLs."""
    return serve_dashboard()


@app.get("/api/v1/health")
def health() -> dict[str, str | bool]:
    from fleet_health.llm import is_llm_enabled

    return {
        "status": "ok",
        "service": "fleet-health-pipeline",
        "llm_enabled": is_llm_enabled(),
    }


@app.get("/api/v1/samples")
def list_sample_datasets() -> list[dict[str, Any]]:
    """Sample CSV bundles available for one-click report generation."""
    if not SAMPLES_DIR.is_dir():
        return []
    datasets: list[dict[str, Any]] = []
    for folder in sorted(SAMPLES_DIR.iterdir()):
        if not folder.is_dir():
            continue
        paths = {
            "noon_path": _norm_path(folder / "noon_reports.csv"),
            "port_schedule_path": _norm_path(folder / "port_schedule.csv"),
            "bunker_path": _norm_path(folder / "bunker_log.csv"),
            "maintenance_path": _norm_path(folder / "maintenance_alerts.csv"),
        }
        if not all(Path(p).is_file() for p in paths.values()):
            continue
        label = folder.name.replace("_", " ").title()
        datasets.append(
            {
                "id": folder.name,
                "label": label,
                "description": _sample_description(folder.name),
                **paths,
            }
        )
    return datasets


def _sample_description(dataset_id: str) -> str:
    descriptions = {
        "fleet": "3 vessels — mixed normal and critical findings",
        "nordic_spirit": "Single vessel (IMO 9345678) — critical defects focus",
    }
    return descriptions.get(dataset_id, f"Sample data in {dataset_id}")


@app.post("/api/v1/reports/generate", response_model=FleetHealthReport)
async def generate_report_paths(body: GenerateFromPathsRequest) -> FleetHealthReport:
    """Generate report from server-local file paths (CLI / testing)."""
    paths = {
        "noon": body.noon_path,
        "port_schedule": body.port_schedule_path,
        "bunker": body.bunker_path,
        "maintenance": body.maintenance_path,
    }
    for key, p in paths.items():
        if not Path(p).is_file():
            raise HTTPException(status_code=400, detail=f"Missing file for {key}: {p}")
    try:
        return await _run_pipeline_async(
            paths, body.vessel_imos, skip_llm=body.fast
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/v1/reports/generate/upload", response_model=FleetHealthReport)
async def generate_report_upload(
    noon: UploadFile = File(...),
    port_schedule: UploadFile = File(...),
    bunker: UploadFile = File(...),
    maintenance: UploadFile = File(...),
    vessel_imos: str = Form(""),
    fast: bool = Form(True),
) -> FleetHealthReport:
    """Upload CSV inputs and run the full agent pipeline."""
    imos = [x.strip() for x in vessel_imos.split(",") if x.strip()]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        paths: dict[str, str] = {}
        for key, upload in [
            ("noon", noon),
            ("port_schedule", port_schedule),
            ("bunker", bunker),
            ("maintenance", maintenance),
        ]:
            dest = tmp_path / f"{key}.csv"
            with dest.open("wb") as f:
                shutil.copyfileobj(upload.file, f)
            paths[key] = str(dest)
        try:
            return await _run_pipeline_async(paths, imos, skip_llm=fast)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/v1/reports")
def list_reports(limit: int = 20) -> list[dict[str, Any]]:
    """Recent reports persisted in SQLite."""
    return MemoryStore().list_reports(limit=min(max(limit, 1), 100))


@app.get("/api/v1/reports/{report_id}", response_model=FleetHealthReport)
def get_report(report_id: str) -> FleetHealthReport:
    report = MemoryStore().get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@app.get("/api/v1/vessels/{imo}/memory")
def vessel_memory(imo: str) -> dict[str, Any]:
    memory = MemoryStore()
    return {
        "imo": imo,
        "baseline": memory.get_baseline(imo),
        "recent_anomalies": memory.get_recent_anomalies(imo),
    }


def _warmup_pipeline() -> None:
    """Import LangGraph + agents once at startup so the first UI click is not slow."""
    sample = SAMPLES_DIR / "fleet"
    paths = {
        "noon": str(sample / "noon_reports.csv"),
        "port_schedule": str(sample / "port_schedule.csv"),
        "bunker": str(sample / "bunker_log.csv"),
        "maintenance": str(sample / "maintenance_alerts.csv"),
    }
    if not all(Path(p).is_file() for p in paths.values()):
        return
    started = time.perf_counter()
    run_pipeline(paths, [], skip_llm=True)
    logger.info("Pipeline warmup finished in %.1fs", time.perf_counter() - started)


@app.on_event("startup")
def _log_dashboard() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    index = _dashboard_index()
    if index.is_file():
        print(f"Fleet Health dashboard: http://127.0.0.1:8000/  (static: {STATIC_DIR})")
    else:
        print(f"WARNING: Dashboard missing at {index}")
    try:
        _warmup_pipeline()
    except Exception as exc:
        logger.warning("Pipeline warmup skipped: %s", exc)


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
else:
    print(f"WARNING: static directory missing: {STATIC_DIR}")
