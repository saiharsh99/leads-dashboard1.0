"""Standalone leads dashboard: upload a daily Excel/CSV lead dump, map columns,
publish the dashboard.

Run:  uvicorn main:app --reload --port 8100   (from leads-dashboard/backend)
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.cors import CORSMiddleware

import analytics
import db
import ingest

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
STATIC_DIR = Path(__file__).parent.parent / "static"

app = FastAPI(title="Leads Dashboard")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

# Preview cache: token -> parsed file, pending commit. In-memory is fine for a
# single-process mini-app; previews are transient by design.
_previews: Dict[str, Dict[str, Any]] = {}


class CommitRequest(BaseModel):
    token: str
    mapping: Dict[str, Optional[str]]


@app.post("/api/uploads/preview")
async def preview_upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds 20 MB limit")
    try:
        df, sheet = ingest.read_table(data, file.filename or "upload")
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    columns = [str(c) for c in df.columns]
    token = str(uuid.uuid4())
    if len(_previews) > 50:
        _previews.clear()
    _previews[token] = {"df": df, "filename": file.filename or "upload"}

    sample = df.head(5).fillna("").astype(str).to_dict(orient="records")
    return {
        "token": token,
        "filename": file.filename,
        "sheet": sheet,
        "row_count": len(df),
        "columns": columns,
        "suggested_mapping": ingest.suggest_mapping(columns),
        "fields": {
            f: {"label": spec["label"], "required": spec["required"]}
            for f, spec in ingest.CANONICAL_FIELDS.items()
        },
        "sample_rows": sample,
    }


@app.post("/api/uploads/commit")
def commit_upload(req: CommitRequest) -> Dict[str, Any]:
    preview = _previews.get(req.token)
    if not preview:
        raise HTTPException(404, "Preview expired — upload the file again")
    try:
        rows = ingest.normalize(preview["df"], req.mapping)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    upload = db.create_upload(preview["filename"], req.mapping, rows)
    del _previews[req.token]
    return upload


@app.get("/api/uploads")
def get_uploads() -> list:
    return db.list_uploads()


@app.delete("/api/uploads/{upload_id}")
def remove_upload(upload_id: str) -> Dict[str, bool]:
    if not db.delete_upload(upload_id):
        raise HTTPException(404, "Upload not found")
    return {"deleted": True}


def _load_leads(upload_id: str) -> list:
    """upload_id: 'latest' (default), 'all' (every appended row), or an upload id."""
    if upload_id == "all":
        return db.fetch_leads(None)
    if upload_id == "latest":
        latest = db.latest_upload_id()
        return db.fetch_leads(latest) if latest else []
    return db.fetch_leads(upload_id)


@app.get("/api/report/overview")
def report_overview(upload_id: str = "latest", anchor: Optional[str] = None) -> Dict[str, Any]:
    """Views 1, 2, 4 — leads count, lead quality, and allocated managers per
    project, each across the FTD / MTD / LTD windows."""
    leads = _load_leads(upload_id)
    if not leads:
        return {"empty": True}
    resolved = analytics.resolve_anchor(leads, anchor)
    return {"empty": False, **analytics.overview(leads, resolved)}


@app.get("/api/report/utm-quality")
def report_utm_quality(
    project: str, upload_id: str = "latest", anchor: Optional[str] = None,
    level: str = "source", filters: Optional[str] = None,
) -> Dict[str, Any]:
    """View 3 — one project, UTM drill-down vs lead quality (FTD/MTD/LTD).

    `filters` is a JSON array of {level, value} pairs from the drill path."""
    leads = _load_leads(upload_id)
    resolved = analytics.resolve_anchor(leads, anchor)
    _validate_level(level)
    return analytics.utm_quality(leads, resolved, project, level, _parse_filters(filters))


@app.get("/api/report/managers")
def report_managers(
    project: str, upload_id: str = "latest", anchor: Optional[str] = None,
    window: str = "ltd",
) -> Dict[str, Any]:
    """View 5 — one project, sales-manager drill-down vs lead quality."""
    leads = _load_leads(upload_id)
    resolved = analytics.resolve_anchor(leads, anchor)
    _validate_window(window)
    return analytics.managers_quality(leads, resolved, project, window)


@app.get("/api/report/lost-utm")
def report_lost_utm(
    project: str, upload_id: str = "latest", anchor: Optional[str] = None,
    window: str = "ltd", level: str = "source",
) -> Dict[str, Any]:
    """View 6 — one project, reason for lost with UTM drill-down vs count."""
    leads = _load_leads(upload_id)
    resolved = analytics.resolve_anchor(leads, anchor)
    _validate_level(level)
    _validate_window(window)
    return analytics.lost_by_utm(leads, resolved, project, window, level)


@app.get("/api/report/attempts-utm")
def report_attempts_utm(
    project: str, upload_id: str = "latest", anchor: Optional[str] = None,
    window: str = "ltd", level: str = "source",
) -> Dict[str, Any]:
    """View 7 — one project, lead quality with UTM drill-down vs no. of attempts."""
    leads = _load_leads(upload_id)
    resolved = analytics.resolve_anchor(leads, anchor)
    _validate_level(level)
    _validate_window(window)
    return analytics.attempts_by_utm(leads, resolved, project, window, level)


def _validate_level(level: str) -> None:
    if level not in analytics.UTM_LEVELS:
        raise HTTPException(400, f"Unknown UTM level: {level}")


def _validate_window(window: str) -> None:
    if window not in analytics.WINDOWS:
        raise HTTPException(400, f"Unknown window: {window}")


def _parse_filters(raw: Optional[str]) -> list:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "filters must be valid JSON")
    if not isinstance(parsed, list) or not all(
        isinstance(f, dict) and f.get("level") in analytics.UTM_LEVELS and "value" in f
        for f in parsed
    ):
        raise HTTPException(400, "filters must be a list of {level, value} objects")
    return parsed


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
