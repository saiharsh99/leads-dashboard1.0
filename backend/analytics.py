"""Report analytics for the 7 dashboard views.

Time windows are anchored on a report date (default: the most recent Created On
in the data, i.e. the day the dump represents):

    FTD  For The Day   — leads created on the anchor date
    MTD  Month To Date — leads created in the anchor's calendar month
    LTD  Life To Date  — all leads, regardless of date

Drill-downs walk the UTM hierarchy source -> campaign -> medium -> term, or the
sales manager assigned to each lead.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

SOURCE_ALIASES = {
    "ig": "Instagram", "instagram": "Instagram", "instagram_feed": "Instagram",
    "instagram_stories": "Instagram", "fb": "Facebook", "facebook": "Facebook",
    "facebook_mobile_feed": "Facebook", "facebook_mobile_reels": "Facebook",
    "google": "Google", "whatsapp": "WhatsApp", "website": "Website",
}

INVALID_REASON = "invalid enquiry"
UTM_LEVELS = ["source", "campaign", "medium", "term"]
UTM_LABELS = {"source": "UTM source", "campaign": "UTM campaign",
              "medium": "UTM medium", "term": "UTM term"}
WINDOWS = ["ftd", "mtd", "ltd"]
NONE_LABEL = "(none)"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _source_name(raw: Optional[str]) -> str:
    if not raw:
        return "Unattributed"
    return SOURCE_ALIASES.get(raw.strip().lower(), raw.strip())


def _utm_value(lead: Dict[str, Any], level: str) -> str:
    if level == "source":
        return _source_name(lead.get("utm_source"))
    field = {"campaign": "utm_campaign", "medium": "utm_medium", "term": "utm_term"}[level]
    val = lead.get(field)
    return val.strip() if val else NONE_LABEL


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def resolve_anchor(leads: List[Dict[str, Any]], anchor: Optional[str]) -> date:
    if anchor:
        try:
            return date.fromisoformat(anchor)
        except ValueError:
            pass
    dates = [d.date() for d in (_parse_dt(r["created_on"]) for r in leads) if d]
    return max(dates) if dates else date.today()


def _in_window(lead: Dict[str, Any], anchor: date, window: str) -> bool:
    if window == "ltd":
        return True
    dt = _parse_dt(lead.get("created_on"))
    if not dt:
        return False
    if window == "mtd":
        return dt.year == anchor.year and dt.month == anchor.month
    if window == "ftd":
        return dt.date() == anchor
    return True


def _rate(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def _quality(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    ql = sum(1 for r in rows if r["ql"] == "QL")
    lost = sum(1 for r in rows if r["ql"] == "Lost")
    return {
        "total": len(rows), "ql": ql, "lost": lost,
        "open": len(rows) - ql - lost, "ql_rate": _rate(ql, len(rows)),
    }


def _windowed_quality(rows: List[Dict[str, Any]], anchor: date) -> Dict[str, Any]:
    return {w: _quality([r for r in rows if _in_window(r, anchor, w)]) for w in WINDOWS}


def _avg_attempts(rows: List[Dict[str, Any]]) -> Optional[float]:
    vals = [r["attempts"] for r in rows if r.get("attempts") is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _project_of(lead: Dict[str, Any]) -> str:
    return lead.get("project") or "Unknown"


def _project_leads(leads: List[Dict[str, Any]], project: str) -> List[Dict[str, Any]]:
    return [r for r in leads if _project_of(r) == project]


def project_names(leads: List[Dict[str, Any]]) -> List[str]:
    counts = Counter(_project_of(r) for r in leads)
    return [name for name, _ in counts.most_common()]


# --------------------------------------------------------------------------- #
# Views 1, 2, 4 — all projects
# --------------------------------------------------------------------------- #
def overview(leads: List[Dict[str, Any]], anchor: date) -> Dict[str, Any]:
    by_project: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for lead in leads:
        by_project[_project_of(lead)].append(lead)

    ordered = sorted(by_project.items(), key=lambda kv: -len(kv[1]))

    view1, view2, view4 = [], [], []
    for name, rows in ordered:
        wq = _windowed_quality(rows, anchor)
        # 1 — leads count per window
        view1.append({"project": name, **{w: wq[w]["total"] for w in WINDOWS}})
        # 2 — lead quality per window
        view2.append({"project": name, "windows": wq})
        # 4 — allocated sales managers
        mgr_counts = Counter(r.get("manager") or "Unassigned" for r in rows)
        view4.append({
            "project": name,
            "manager_count": len(mgr_counts),
            "total": len(rows),
            "managers": [{"name": m, "total": c} for m, c in mgr_counts.most_common()],
        })

    totals = _windowed_quality(leads, anchor)
    return {
        "anchor": anchor.isoformat(),
        "projects": [name for name, _ in ordered],
        "totals": {w: totals[w] for w in WINDOWS},
        "view1": view1,
        "view2": view2,
        "view4": view4,
    }


# --------------------------------------------------------------------------- #
# View 3 — project + UTM drill vs lead quality (LTD/MTD/FTD)
# --------------------------------------------------------------------------- #
def utm_quality(leads: List[Dict[str, Any]], anchor: date, project: str,
                level: str, filters: List[Dict[str, str]]) -> Dict[str, Any]:
    pool = _project_leads(leads, project)
    for flt in filters:
        pool = [r for r in pool if _utm_value(r, flt["level"]) == flt["value"]]

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for lead in pool:
        groups[_utm_value(lead, level)].append(lead)

    rows = [{"value": val, "windows": _windowed_quality(rs, anchor)}
            for val, rs in groups.items()]
    rows.sort(key=lambda r: -r["windows"]["ltd"]["total"])

    idx = UTM_LEVELS.index(level)
    return {
        "project": project,
        "level": level,
        "level_label": UTM_LABELS[level],
        "filters": filters,
        "next_level": UTM_LEVELS[idx + 1] if idx + 1 < len(UTM_LEVELS) else None,
        "rows": rows,
    }


# --------------------------------------------------------------------------- #
# View 5 — project + sales manager drill vs lead quality
# --------------------------------------------------------------------------- #
def managers_quality(leads: List[Dict[str, Any]], anchor: date, project: str,
                     window: str) -> Dict[str, Any]:
    pool = [r for r in _project_leads(leads, project) if _in_window(r, anchor, window)]
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for lead in pool:
        groups[lead.get("manager") or "Unassigned"].append(lead)

    rows = [{"manager": m, **_quality(rs), "avg_attempts": _avg_attempts(rs)}
            for m, rs in groups.items()]
    rows.sort(key=lambda r: -r["total"])
    return {"project": project, "window": window, "rows": rows}


# --------------------------------------------------------------------------- #
# View 6 — project + reason for lost, UTM drill vs count
# --------------------------------------------------------------------------- #
def lost_by_utm(leads: List[Dict[str, Any]], anchor: date, project: str,
                window: str, level: str, top_utm: int = 6) -> Dict[str, Any]:
    lost = [r for r in _project_leads(leads, project)
            if r["ql"] == "Lost" and _in_window(r, anchor, window)]

    utm_totals = Counter(_utm_value(r, level) for r in lost)
    top_values = [v for v, _ in utm_totals.most_common(top_utm)]
    has_other = len(utm_totals) > len(top_values)
    columns = top_values + (["Other"] if has_other else [])

    by_reason: Dict[str, Counter] = defaultdict(Counter)
    for lead in lost:
        reason = lead.get("lost_reason") or "Not recorded"
        val = _utm_value(lead, level)
        by_reason[reason][val if val in top_values else "Other"] += 1

    reasons = []
    for reason, counter in by_reason.items():
        reasons.append({
            "reason": reason,
            "total": sum(counter.values()),
            "segments": {col: counter.get(col, 0) for col in columns},
        })
    reasons.sort(key=lambda r: -r["total"])

    return {
        "project": project, "window": window, "level": level,
        "level_label": UTM_LABELS[level], "columns": columns,
        "total_lost": len(lost), "reasons": reasons,
    }


# --------------------------------------------------------------------------- #
# View 7 — project + lead quality, UTM drill vs no. of attempts
# --------------------------------------------------------------------------- #
def attempts_by_utm(leads: List[Dict[str, Any]], anchor: date, project: str,
                    window: str, level: str, top_utm: int = 12) -> Dict[str, Any]:
    pool = [r for r in _project_leads(leads, project) if _in_window(r, anchor, window)]

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for lead in pool:
        groups[_utm_value(lead, level)].append(lead)

    ranked = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:top_utm]

    rows = []
    for val, rs in ranked:
        quality = {}
        for bucket in ("QL", "Open", "Lost"):
            b = [r for r in rs if r["ql"] == bucket]
            quality[bucket] = {"avg_attempts": _avg_attempts(b), "count": len(b)}
        rows.append({
            "value": val, "total": len(rs),
            "avg_attempts": _avg_attempts(rs), "quality": quality,
        })

    return {
        "project": project, "window": window, "level": level,
        "level_label": UTM_LABELS[level], "rows": rows,
    }
