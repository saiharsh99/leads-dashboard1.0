# Leads Dashboard

Standalone mini-app for publishing a daily leads dashboard from a CRM lead
dump (Excel or CSV). Upload the file, map its columns once, and the dashboard
is live — KPIs, weekly lead flow, source quality, projects, lost reasons,
manager performance, and a campaign scorecard.

## Run

```bash
cd leads-dashboard
pip install -r requirements.txt
cd backend
uvicorn main:app --port 8100
```

Open http://localhost:8100 — upload today's dump, confirm the suggested
column mapping, and hit **Publish dashboard**.

## How it works

- **Upload** (`POST /api/uploads/preview`): parses `.xlsx`/`.xls`/`.csv`
  (for workbooks, the sheet with the most rows is used), returns detected
  columns, sample rows, and a best-guess mapping to the dashboard's fields.
- **Column mapping**: only *Created date* and *Qualification status* are
  required; everything else is optional and simply hidden from metrics when
  unmapped. The suggested mapping is editable before publishing.
- **Commit** (`POST /api/uploads/commit`): normalizes rows (CRM `0`
  placeholders → blank, dates parsed, qualification labels bucketed into
  QL / Lost / Open) and appends them to SQLite (`backend/leads.db`, or set
  `LEADS_DB_PATH`).
- **Dashboard** (`GET /api/dashboard?upload_id=latest|all|<id>`): computes
  all metrics server-side. Every upload is kept (append model); the UI
  defaults to the newest upload and offers "All uploads combined" plus an
  upload history with per-file delete.

## Daily routine

1. Export the fresh-leads dump from the CRM.
2. Open the app, click **Upload dump**, drop the file.
3. Check the mapping (it remembers nothing between files by design — the
   suggestions re-derive from the columns, so renamed exports still work).
4. Publish. The dashboard URL always shows the latest upload.

## Tests

```bash
cd leads-dashboard
python -m pytest tests -q
```
