"""Request ids, per-operation processing logs, the log/diagnostics endpoints and verbose error responses."""
import io

import pytest

from tests.pdf_samples import make_mark_scheme, make_question_paper


@pytest.fixture(autouse=True)
def _clean(client):
    for s in client.get("/api/question-sets").json():
        client.delete(f"/api/question-sets/{s['id']}")
    for p in client.get("/api/past-papers").json():
        client.delete(f"/api/past-papers/{p['id']}")


def _upload(client, tmp_path, request_id=None):
    qp = make_question_paper(tmp_path / "qp.pdf")
    ms = make_mark_scheme(tmp_path / "ms.pdf")
    headers = {"X-Request-ID": request_id} if request_id else {}
    return client.post(
        "/api/past-papers",
        files={
            "question_paper": ("qp.pdf", qp.read_bytes(), "application/pdf"),
            "mark_scheme": ("ms.pdf", ms.read_bytes(), "application/pdf"),
        },
        headers=headers,
    )


def test_every_response_carries_a_request_id(client):
    resp = client.get("/api/past-papers")
    assert len(resp.headers["X-Request-ID"]) >= 4
    supplied = client.get("/api/past-papers", headers={"X-Request-ID": "ui-test-123"})
    assert supplied.headers["X-Request-ID"] == "ui-test-123"
    bad = client.get("/api/past-papers", headers={"X-Request-ID": "has spaces & symbols!"})
    assert bad.headers["X-Request-ID"] != "has spaces & symbols!"


def test_import_stores_a_step_by_step_processing_log(client, tmp_path):
    paper = _upload(client, tmp_path).json()
    log = "\n".join(paper["processing_log"])
    for expected in (
        "Step 1/4",
        "Question-number column",
        "Q1: 2 mark(s)",
        "Mark scheme parsed: 6 row(s)",
        "Total check: questions add up to 10 = mark scheme maximum",
        "Import finished",
    ):
        assert expected in log, expected
    # Persisted, not just returned once.
    again = client.get(f"/api/past-papers/{paper['id']}").json()
    assert again["processing_log"] == paper["processing_log"]


def test_logs_endpoint_follows_one_request(client, tmp_path):
    _upload(client, tmp_path, request_id="trace-import-1")
    entries = client.get("/api/logs", params={"request_id": "trace-import-1", "limit": 500}).json()["entries"]
    messages = [e["message"] for e in entries]
    assert any("Importing past paper" in m for m in messages)
    assert any(m.startswith("← POST /api/past-papers 200") for m in messages)
    assert all(e["request_id"] == "trace-import-1" for e in entries)

    warnings_only = client.get("/api/logs", params={"level": "WARNING", "limit": 5000}).json()["entries"]
    assert all(e["level"] in ("WARNING", "ERROR", "CRITICAL") for e in warnings_only)


def test_bank_set_and_grading_logs(client, tmp_path):
    _upload(client, tmp_path)
    (qs,) = client.post("/api/question-sets/from-bank", json={"target_marks": 5}).json()
    set_log = "\n".join(qs["processing_log"])
    assert "Building 1 set(s) of 5 marks" in set_log and "Set 1: picked" in set_log

    sub = client.post(
        "/api/submissions",
        data={"question_set_id": qs["id"]},
        files={"images": ("answer.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    ).json()
    graded = client.post(f"/api/submissions/{sub['id']}/evaluate").json()
    grading_log = "\n".join(graded["processing_log"])
    assert "Grading submission" in grading_log
    assert "MOCK MODE" in grading_log
    assert "Graded: 0 / 5 (mock)" in grading_log


def test_errors_are_verbose(client, monkeypatch):
    missing = client.get("/api/past-papers/99999")
    assert missing.status_code == 404
    assert missing.json()["request_id"] == missing.headers["X-Request-ID"]

    invalid = client.post("/api/question-sets/from-bank", json={"target_marks": -5})
    assert invalid.status_code == 422
    assert invalid.json()["detail"][0]["loc"][-1] == "target_marks"

    def explode(*args, **kwargs):
        raise RuntimeError("synthetic failure for the test")

    monkeypatch.setattr("app.routers.question_sets.build_bank_sets", explode)
    crashed = client.post("/api/question-sets/from-bank", json={"target_marks": 5})
    body = crashed.json()
    assert crashed.status_code == 500
    assert body["error_type"] == "RuntimeError"
    assert "synthetic failure for the test" in body["detail"]
    assert any("synthetic failure" in line for line in body["traceback"])
    entries = client.get("/api/logs", params={"request_id": body["request_id"]}).json()["entries"]
    assert any("crashed" in e["message"] and "Traceback" in e["message"] for e in entries)


def test_diagnostics(client):
    d = client.get("/api/diagnostics").json()
    assert d["mock_mode"] is True
    assert d["packages"]["pymupdf"] != "not installed"
    assert set(d["counts"]) >= {"past_papers", "bank_questions", "question_sets"}
    assert client.get("/api/logs/download").status_code == 200
