"""End-to-end tests: upload preview → mapping → commit → dashboard."""
import io
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEADS_DB_PATH", str(tmp_path / "test.db"))
    for mod in ("db", "ingest", "analytics", "main"):
        sys.modules.pop(mod, None)
    import db as db_module
    db_module.DB_PATH = tmp_path / "test.db"
    import main
    return TestClient(main.app)


def sample_xlsx() -> bytes:
    df = pd.DataFrame({
        "Sl No": [1, 2, 3, 4],
        "Opportunity Name": ["A - P1", "B - P1", "C - P2", "D - P2"],
        "Manager (User Name)": ["Riya", "Riya", "Sam", "Sam"],
        "Created On": ["2026-07-01 10:00", "2026-07-02 11:00", "2026-07-08 12:00", 0],
        "QL": ["QL", "Lost", "Open", "Lost"],
        "No. of Site Visits": [1, 0, 0, 0],
        "UTM Source - Name": ["ig", "fb", "ig", 0],
        "UTM Source - UTM Campaign": ["Camp1"] * 4,
        "Reason for Lost": [0, "Invalid Enquiry", 0, "Not Interested"],
        "Number of Attempts": [3, 5, 0, 2],
        "Project Name": ["P1", "P1", "P2", "P2"],
    })
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def do_upload(client, data=None, name="dump.xlsx"):
    res = client.post("/api/uploads/preview",
                      files={"file": (name, data or sample_xlsx(),
                                      "application/octet-stream")})
    assert res.status_code == 200, res.text
    return res.json()


def test_preview_suggests_mapping(client):
    p = do_upload(client)
    m = p["suggested_mapping"]
    assert m["created_on"] == "Created On"
    assert m["ql"] == "QL"
    assert m["utm_source"] == "UTM Source - Name"
    assert m["project"] == "Project Name"
    assert m["manager"] == "Manager (User Name)"
    assert p["row_count"] == 4


def commit_sample(client):
    p = do_upload(client)
    res = client.post("/api/uploads/commit",
                      json={"token": p["token"], "mapping": p["suggested_mapping"]})
    assert res.status_code == 200, res.text
    return res.json()


def test_overview_views(client):
    commit_sample(client)
    ov = client.get("/api/report/overview").json()
    assert ov["empty"] is False
    assert ov["anchor"] == "2026-07-08"          # latest dated lead
    assert set(ov["projects"]) == {"P1", "P2"}
    assert ov["totals"]["ltd"]["total"] == 4

    # View 1 — leads count per window
    v1 = {r["project"]: r for r in ov["view1"]}
    assert v1["P1"]["ltd"] == 2 and v1["P2"]["ltd"] == 2
    assert v1["P2"]["ftd"] == 1                   # only C is on 2026-07-08
    assert v1["P1"]["ftd"] == 0

    # View 2 — quality per window
    v2 = {r["project"]: r for r in ov["view2"]}
    assert v2["P1"]["windows"]["ltd"]["ql"] == 1
    assert v2["P1"]["windows"]["ltd"]["lost"] == 1

    # View 4 — allocated managers
    v4 = {r["project"]: r for r in ov["view4"]}
    assert v4["P1"]["manager_count"] == 1
    assert v4["P1"]["managers"][0]["name"] == "Riya"


def test_utm_quality_drill(client):
    commit_sample(client)
    top = client.get("/api/report/utm-quality",
                     params={"project": "P1", "level": "source"}).json()
    assert top["next_level"] == "campaign"
    vals = {r["value"] for r in top["rows"]}
    assert {"Instagram", "Facebook"} <= vals

    drilled = client.get("/api/report/utm-quality", params={
        "project": "P1", "level": "campaign",
        "filters": '[{"level": "source", "value": "Instagram"}]',
    }).json()
    assert all(r["windows"]["ltd"]["total"] >= 1 for r in drilled["rows"])


def test_managers_lost_attempts(client):
    commit_sample(client)
    mgr = client.get("/api/report/managers",
                     params={"project": "P1", "window": "ltd"}).json()
    assert mgr["rows"][0]["manager"] == "Riya"
    assert mgr["rows"][0]["total"] == 2

    lost = client.get("/api/report/lost-utm",
                      params={"project": "P1", "window": "ltd", "level": "source"}).json()
    assert lost["total_lost"] == 1
    assert lost["reasons"][0]["reason"] == "Invalid Enquiry"

    att = client.get("/api/report/attempts-utm",
                     params={"project": "P1", "window": "ltd", "level": "source"}).json()
    assert att["rows"]  # at least one UTM group with attempts


def test_bad_params_rejected(client):
    commit_sample(client)
    assert client.get("/api/report/managers",
                      params={"project": "P1", "window": "xxx"}).status_code == 400
    assert client.get("/api/report/lost-utm",
                      params={"project": "P1", "level": "bogus"}).status_code == 400
    assert client.get("/api/report/utm-quality",
                      params={"project": "P1", "filters": "not-json"}).status_code == 400


def test_missing_required_mapping_rejected(client):
    p = do_upload(client)
    mapping = dict(p["suggested_mapping"], created_on=None)
    res = client.post("/api/uploads/commit", json={"token": p["token"], "mapping": mapping})
    assert res.status_code == 400
    assert "Created date" in res.json()["detail"]


def test_csv_and_append_model(client):
    csv = b"Created On,Lead Status\n2026-07-01,Qualified\n2026-07-02,Closed - Lost\n"
    p = do_upload(client, data=csv, name="dump.csv")
    m = p["suggested_mapping"]
    assert m["created_on"] == "Created On" and m["ql"] == "Lead Status"
    client.post("/api/uploads/commit", json={"token": p["token"], "mapping": m})

    p2 = do_upload(client)
    client.post("/api/uploads/commit",
                json={"token": p2["token"], "mapping": p2["suggested_mapping"]})

    assert len(client.get("/api/uploads").json()) == 2
    assert client.get("/api/report/overview?upload_id=all").json()["totals"]["ltd"]["total"] == 6
    assert client.get("/api/report/overview?upload_id=latest").json()["totals"]["ltd"]["total"] == 4


def test_ql_bucketing(client):
    csv = (b"Created On,Lead Status\n"
           b"2026-07-01,Qualified/Interested\n"
           b"2026-07-01,Closed - Lost\n"
           b"2026-07-01,Followup\n")
    p = do_upload(client, data=csv, name="s.csv")
    client.post("/api/uploads/commit",
                json={"token": p["token"], "mapping": p["suggested_mapping"]})
    q = client.get("/api/report/overview").json()["totals"]["ltd"]
    assert (q["ql"], q["lost"], q["open"]) == (1, 1, 1)


def test_delete_upload(client):
    p = do_upload(client)
    up = client.post("/api/uploads/commit",
                     json={"token": p["token"], "mapping": p["suggested_mapping"]}).json()
    assert client.delete(f"/api/uploads/{up['id']}").status_code == 200
    assert client.get("/api/report/overview").json()["empty"] is True


def test_unsupported_file_rejected(client):
    res = client.post("/api/uploads/preview",
                      files={"file": ("dump.pdf", b"%PDF", "application/pdf")})
    assert res.status_code == 400
