"""Parse Excel/CSV lead dumps, suggest column mappings, normalize rows.

CRM exports frequently use 0 / "0" as an empty-cell placeholder; normalization
treats those as missing.
"""
from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# Canonical fields the dashboard consumes. Each entry: (label, required, synonyms)
CANONICAL_FIELDS: Dict[str, Dict[str, Any]] = {
    "name":         {"label": "Lead name", "required": False,
                     "synonyms": ["opportunity name", "object name", "lead name", "customer", "contact"]},
    "manager":      {"label": "Manager / owner", "required": False,
                     "synonyms": ["manager", "user name", "owner", "assigned to", "agent", "executive"]},
    "created_on":   {"label": "Created date", "required": True,
                     "synonyms": ["created on", "created at", "create date", "date", "lead date", "enquiry date"]},
    "ql":           {"label": "Qualification status", "required": True,
                     "synonyms": ["ql", "qualification", "lead status", "status", "disposition"]},
    "stage":        {"label": "Stage", "required": False,
                     "synonyms": ["stage", "pipeline stage", "funnel stage"]},
    "site_visits":  {"label": "No. of site visits", "required": False,
                     "synonyms": ["site visits", "no. of site visits", "visits", "sv count"]},
    "utm_campaign": {"label": "UTM campaign", "required": False,
                     "synonyms": ["utm campaign", "campaign", "campaign name"]},
    "utm_medium":   {"label": "UTM medium", "required": False,
                     "synonyms": ["utm medium", "medium", "ad set", "adset"]},
    "utm_source":   {"label": "UTM source", "required": False,
                     "synonyms": ["utm source - name", "utm source", "source", "lead source", "channel"]},
    "utm_term":     {"label": "UTM term", "required": False,
                     "synonyms": ["utm term", "term", "audience", "keyword"]},
    "call_status":  {"label": "Last call status", "required": False,
                     "synonyms": ["last call attempted status", "call status", "call disposition", "last call"]},
    "lost_reason":  {"label": "Reason for lost", "required": False,
                     "synonyms": ["reason for lost", "lost reason", "reason", "closed lost reason"]},
    "attempts":     {"label": "Number of attempts", "required": False,
                     "synonyms": ["number of attempts", "attempts", "call attempts", "no of attempts"]},
    "project":      {"label": "Project", "required": False,
                     "synonyms": ["project name", "project", "property", "development"]},
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).strip()


def read_table(data: bytes, filename: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Return (dataframe, sheet_name). For workbooks, pick the sheet with the
    most data rows — exports often carry pivot/summary sheets alongside the dump."""
    lower = filename.lower()
    if lower.endswith((".xlsx", ".xls", ".xlsm")):
        xl = pd.ExcelFile(io.BytesIO(data))
        best_df, best_sheet = None, None
        for sheet in xl.sheet_names:
            df = xl.parse(sheet)
            if best_df is None or len(df.dropna(how="all")) > len(best_df.dropna(how="all")):
                best_df, best_sheet = df, sheet
        if best_df is None:
            raise ValueError("Workbook has no sheets")
        return best_df, best_sheet
    if lower.endswith((".csv", ".txt")):
        return pd.read_csv(io.BytesIO(data)), None
    raise ValueError(f"Unsupported file type: {filename} (expected .xlsx, .xls, or .csv)")


def suggest_mapping(columns: List[str]) -> Dict[str, Optional[str]]:
    """Best-guess source column for each canonical field; None when no match."""
    normed = {col: _norm(col) for col in columns}
    mapping: Dict[str, Optional[str]] = {}
    taken: set = set()
    for field, spec in CANONICAL_FIELDS.items():
        best, best_score = None, 0
        for col, ncol in normed.items():
            if col in taken:
                continue
            for rank, syn in enumerate(spec["synonyms"]):
                if ncol == syn:
                    score = 1000 - rank
                elif syn in ncol:
                    score = 500 - rank - abs(len(ncol) - len(syn))
                else:
                    continue
                if score > best_score:
                    best, best_score = col, score
        mapping[field] = best
        if best:
            taken.add(best)
    return mapping


_PLACEHOLDERS = {"", "0", "0.0", "nan", "none", "null", "-"}


def _clean(value: Any) -> Optional[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    return None if s.lower() in _PLACEHOLDERS else s


def _to_int(value: Any) -> Optional[int]:
    s = _clean(value)
    if s is None:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _ql_bucket(value: Optional[str]) -> Optional[str]:
    """Normalize free-form qualification labels into QL / Lost / Open."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("ql", "qualified") or "qualif" in v:
        return "QL"
    if "lost" in v or "closed" in v or "junk" in v or "invalid" in v:
        return "Lost"
    return "Open"


def normalize(df: pd.DataFrame, mapping: Dict[str, Optional[str]]) -> List[Dict[str, Any]]:
    missing = [f for f, spec in CANONICAL_FIELDS.items()
               if spec["required"] and not mapping.get(f)]
    if missing:
        labels = ", ".join(CANONICAL_FIELDS[f]["label"] for f in missing)
        raise ValueError(f"Required fields not mapped: {labels}")

    unknown = [c for c in mapping.values() if c and c not in df.columns]
    if unknown:
        raise ValueError(f"Mapped columns not in file: {', '.join(unknown)}")

    rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        def get(field: str) -> Optional[str]:
            col = mapping.get(field)
            return _clean(r[col]) if col else None

        created = get("created_on")
        if created:
            parsed = pd.to_datetime(created, errors="coerce", dayfirst=False)
            created = parsed.isoformat() if not pd.isna(parsed) else None
        if not created and not get("name") and not get("ql"):
            continue  # fully blank row

        rows.append({
            "name": get("name"),
            "manager": get("manager"),
            "created_on": created,
            "ql": _ql_bucket(get("ql")),
            "stage": get("stage"),
            "site_visits": _to_int(r[mapping["site_visits"]]) if mapping.get("site_visits") else None,
            "utm_campaign": get("utm_campaign"),
            "utm_medium": get("utm_medium"),
            "utm_source": get("utm_source"),
            "utm_term": get("utm_term"),
            "call_status": get("call_status"),
            "lost_reason": get("lost_reason"),
            "attempts": _to_int(r[mapping["attempts"]]) if mapping.get("attempts") else None,
            "project": get("project"),
        })
    if not rows:
        raise ValueError("No usable rows found in the file")
    return rows
