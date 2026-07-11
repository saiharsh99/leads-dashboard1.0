"""SQLite storage for lead dumps. Standalone — no external DB required."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(os.environ.get("LEADS_DB_PATH", Path(__file__).parent / "leads.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    mapping TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    upload_id TEXT NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    name TEXT,
    manager TEXT,
    created_on TEXT,
    ql TEXT,
    stage TEXT,
    site_visits INTEGER,
    utm_campaign TEXT,
    utm_medium TEXT,
    utm_source TEXT,
    utm_term TEXT,
    call_status TEXT,
    lost_reason TEXT,
    attempts INTEGER,
    project TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_upload ON leads(upload_id);
"""

LEAD_COLUMNS = [
    "name", "manager", "created_on", "ql", "stage", "site_visits",
    "utm_campaign", "utm_medium", "utm_source", "utm_term",
    "call_status", "lost_reason", "attempts", "project",
]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def create_upload(filename: str, mapping: Dict[str, str], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    upload = {
        "id": str(uuid.uuid4()),
        "filename": filename,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "mapping": mapping,
    }
    with connect() as conn:
        conn.execute(
            "INSERT INTO uploads (id, filename, uploaded_at, row_count, mapping) VALUES (?,?,?,?,?)",
            (upload["id"], filename, upload["uploaded_at"], len(rows), json.dumps(mapping)),
        )
        conn.executemany(
            f"INSERT INTO leads (id, upload_id, {', '.join(LEAD_COLUMNS)}) "
            f"VALUES (?, ?, {', '.join('?' * len(LEAD_COLUMNS))})",
            [
                (str(uuid.uuid4()), upload["id"], *[row.get(c) for c in LEAD_COLUMNS])
                for row in rows
            ],
        )
    return upload


def list_uploads() -> List[Dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM uploads ORDER BY uploaded_at DESC").fetchall()
    return [{**dict(r), "mapping": json.loads(r["mapping"])} for r in rows]


def delete_upload(upload_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
    return cur.rowcount > 0


def fetch_leads(upload_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """upload_id=None returns every appended row; otherwise one upload's rows."""
    with connect() as conn:
        if upload_id:
            rows = conn.execute("SELECT * FROM leads WHERE upload_id = ?", (upload_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM leads").fetchall()
    return [dict(r) for r in rows]


def latest_upload_id() -> Optional[str]:
    with connect() as conn:
        row = conn.execute("SELECT id FROM uploads ORDER BY uploaded_at DESC LIMIT 1").fetchone()
    return row["id"] if row else None
