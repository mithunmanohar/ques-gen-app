"""
Past-paper bank: extraction, mark-scheme parsing, automatic checks, building
sets from the bank, and grading a bank set — all against synthetic PDFs from
pdf_samples.py, in mock mode (see conftest.py).
"""
import io

import pymupdf
import pytest

from app.services import bank_sets
from app.services.mark_scheme import numeric_marks, parse_mark_scheme
from app.services.paper_extraction import extract_questions, render_segments

from tests.pdf_samples import make_mark_scheme, make_question_paper


@pytest.fixture()
def qp_pdf(tmp_path):
    return make_question_paper(tmp_path / "qp.pdf")


@pytest.fixture()
def ms_pdf(tmp_path):
    return make_mark_scheme(tmp_path / "ms.pdf")


def _upload(client, qp_pdf, ms_pdf=None, **form):
    files = {"question_paper": ("0444_s23_qp_21.pdf", qp_pdf.read_bytes(), "application/pdf")}
    if ms_pdf is not None:
        files["mark_scheme"] = ("0444_s23_ms_21.pdf", ms_pdf.read_bytes(), "application/pdf")
    resp = client.post("/api/past-papers", data={"subject": "Mathematics", **form}, files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture(autouse=True)
def _clean_bank(client):
    """Each test starts with an empty bank (the test DB is shared across the session)."""
    for s in client.get("/api/question-sets").json():
        client.delete(f"/api/question-sets/{s['id']}")
    for p in client.get("/api/past-papers").json():
        client.delete(f"/api/past-papers/{p['id']}")


# ---------- extraction ----------


def test_extracts_each_question_in_order_and_ignores_cover_digits(qp_pdf):
    result = extract_questions(qp_pdf)
    assert [q.number for q in result.questions] == [1, 2, 3, 4]
    assert result.issues == []
    assert result.info.label == "0444/21 May/June 2023"


def test_question_content_marks_and_subparts(qp_pdf):
    q1, q2, q3, q4 = extract_questions(qp_pdf).questions
    assert [q.marks for q in (q1, q2, q3, q4)] == [2, 3, 3, 2]
    assert q2.subparts == ["a", "b"]
    assert "Find angle ABC." in q1.text
    assert not q1.text.startswith("1")  # original question number removed


def test_question_continuing_on_next_page_is_stitched(qp_pdf):
    q3 = extract_questions(qp_pdf).questions[2]
    assert [s.page for s in q3.segments] == [1, 2]
    assert "Write down the value of x + 1." in q3.text
    assert "printed on the next page" not in q3.text  # boilerplate dropped


def test_crop_excludes_blank_answer_space_and_next_question(qp_pdf):
    q1, q2, *_ = extract_questions(qp_pdf).questions
    (seg1,) = q1.segments
    (seg2,) = q2.segments
    assert seg1.rect.y1 < seg2.rect.y0  # no overlap
    assert seg1.rect.y1 < 310  # stops just under Q1's "[2]" line (baseline 300), not at Q2 (y≈350)


def test_last_question_ignores_blank_page(qp_pdf):
    q4 = extract_questions(qp_pdf).questions[3]
    assert [s.page for s in q4.segments] == [2]


def test_render_produces_png_with_number_masked(qp_pdf, tmp_path):
    q1 = extract_questions(qp_pdf).questions[0]
    out = tmp_path / "q1.png"
    render_segments(qp_pdf, q1.segments, out)
    pix = pymupdf.Pixmap(str(out))
    assert pix.width > 1000 and pix.height > 200
    # The masked question-number area is plain white.
    seg = q1.segments[0]
    scale = pix.width / seg.rect.width
    mx = int((seg.mask.x0 - seg.rect.x0 + seg.mask.width / 2) * scale)
    my = int((seg.mask.y0 - seg.rect.y0 + seg.mask.height / 2) * scale)
    assert pix.pixel(mx, my)[:3] == (255, 255, 255)


def test_scanned_pdf_is_rejected_clearly(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "scan.pdf"
    doc.save(path)
    with pytest.raises(ValueError, match="no text layer"):
        extract_questions(path)


# ---------- mark scheme ----------


def test_mark_scheme_rows_and_max_mark(ms_pdf):
    ms = parse_mark_scheme(ms_pdf)
    assert ms.max_mark == 10
    assert (ms.syllabus_code, ms.component, ms.session, ms.year) == ("0444", "21", "May/June", "2023")
    assert [r.label for r in ms.rows] == ["1", "2(a)", "2(b)", "3(a)", "3(b)", "4"]
    q2 = ms.rows_for(2)
    assert [(r.answer, r.marks) for r in q2] == [("7", "1"), ("30", "2")]
    assert q2[1].partial_marks == "M1 for 5 x 6"


@pytest.mark.parametrize(
    "cells, expected",
    [(["2"], 2), (["2 2"], 4), (["M1 A1"], 2), (["2 B1", "1"], 4), (["1FT"], 1), (["SC1"], None), ([""], None)],
)
def test_numeric_marks(cells, expected):
    class Row:
        def __init__(self, marks):
            self.marks = marks

    assert numeric_marks([Row(c) for c in cells]) == expected


# ---------- import + automatic checks (API) ----------


def test_upload_pair_builds_bank_with_answers_and_no_warnings(client, qp_pdf, ms_pdf):
    paper = _upload(client, qp_pdf, ms_pdf)
    assert paper["status"] == "ready"
    assert paper["title"] == "0444/21 May/June 2023"
    assert paper["paper_code"] == "0444/21 May/June 2023"
    assert (paper["question_count"], paper["total_marks"], paper["max_mark"]) == (4, 10, 10)
    assert paper["issues"] == [] and paper["needs_attention"] is False

    q2 = paper["questions"][1]
    assert q2["flags"] == []
    assert [e["label"] for e in q2["ms_entries"]] == ["2(a)", "2(b)"]
    assert client.get(q2["image_url"]).headers["content-type"] == "image/png"
    assert client.get(q2["ms_image_url"]).status_code == 200


def test_checks_flag_mismatches_without_blocking(client, qp_pdf, tmp_path):
    wrong_ms = make_mark_scheme(tmp_path / "wrong.pdf", max_mark=12, code="0444/22")
    paper = _upload(client, qp_pdf, wrong_ms)
    assert paper["status"] == "ready" and paper["question_count"] == 4
    issues = " ".join(paper["issues"])
    assert "add up to 10, but the mark scheme's maximum is 12" in issues
    assert "0444/22" in issues  # paper/mark-scheme pairing mismatch
    assert paper["needs_attention"] is True


def test_upload_without_mark_scheme_notes_it(client, qp_pdf):
    paper = _upload(client, qp_pdf)
    assert paper["status"] == "ready"
    assert any("No mark scheme" in i for i in paper["issues"])
    assert all(q["ms_entries"] == [] and q["ms_image_url"] is None for q in paper["questions"])


def test_duplicate_paper_is_refused(client, qp_pdf, ms_pdf):
    _upload(client, qp_pdf, ms_pdf)
    again = _upload(client, qp_pdf, ms_pdf)
    assert again["status"] == "failed"
    assert "already in the bank" in again["issues"][0]


def test_non_pdf_upload_rejected(client):
    resp = client.post("/api/past-papers", files={"question_paper": ("paper.txt", b"hi", "text/plain")})
    assert resp.status_code == 400


# ---------- building sets from the bank ----------


def test_from_bank_hits_target_and_serves_images(client, qp_pdf, ms_pdf):
    _upload(client, qp_pdf, ms_pdf)
    resp = client.post("/api/question-sets/from-bank", json={"target_marks": 5, "num_sets": 1})
    assert resp.status_code == 200, resp.text
    (qs,) = resp.json()
    assert qs["source"] == "bank" and qs["pattern_id"] is None and qs["status"] == "ready"
    assert sum(q["marks"] for q in qs["questions"]) == 5
    assert all(q["image_url"] for q in qs["questions"])
    assert "expected_answer" not in qs["questions"][0]  # student view hides the key

    key = client.get(f"/api/question-sets/{qs['id']}/answer-key").json()
    assert all(q["expected_answer"] and q["answer_key_image_url"] for q in key["questions"])
    assert key["questions"][0]["source_label"].startswith("0444/21 May/June 2023 Q")


def test_from_bank_sets_never_repeat_and_avoid_used(client, qp_pdf, ms_pdf):
    _upload(client, qp_pdf, ms_pdf)
    first = client.post("/api/question-sets/from-bank", json={"target_marks": 5, "num_sets": 2}).json()
    ids = [q["image_url"] for s in first for q in s["questions"]]
    assert len(ids) == len(set(ids))
    assert sum(q["marks"] for s in first for q in s["questions"]) == 10  # whole bank used

    # Every question is now used, so nothing is left unless reuse is allowed.
    assert client.post("/api/question-sets/from-bank", json={"target_marks": 5}).status_code == 400
    reuse = client.post("/api/question-sets/from-bank", json={"target_marks": 5, "avoid_used": False})
    assert reuse.status_code == 200


def test_from_bank_reports_shortfall(client, qp_pdf, ms_pdf):
    _upload(client, qp_pdf, ms_pdf)
    (qs,) = client.post("/api/question-sets/from-bank", json={"target_marks": 50}).json()
    assert qs["status"] == "ready"
    assert "Reached 10 of the 50 marks" in qs["error_message"]


def test_flagged_questions_excluded_by_default(client, qp_pdf, tmp_path):
    _upload(client, qp_pdf)  # no mark scheme: questions aren't flagged, paper has an issue
    paper = client.get("/api/past-papers").json()[0]
    detail = client.get(f"/api/past-papers/{paper['id']}").json()
    assert all(q["flags"] == [] for q in detail["questions"])

    from app.db import SessionLocal
    from app import models

    with SessionLocal() as db:
        for bq in db.query(models.BankQuestion).all():
            bq.flags = ["synthetic flag"]
        db.commit()
    assert client.post("/api/question-sets/from-bank", json={"target_marks": 5}).status_code == 400
    ok = client.post("/api/question-sets/from-bank", json={"target_marks": 5, "include_flagged": True})
    assert ok.status_code == 200


def test_topic_filter(client, qp_pdf, ms_pdf):
    paper = _upload(client, qp_pdf, ms_pdf)
    from app.db import SessionLocal
    from app import models

    with SessionLocal() as db:
        for bq in db.query(models.BankQuestion).filter_by(past_paper_id=paper["id"]).all():
            bq.topics = ["Algebra"] if bq.number in (3, 4) else ["Geometry"]
        db.commit()

    topics = {t["topic"]: t["count"] for t in client.get("/api/bank-questions/topics").json()}
    assert topics == {"Algebra": 2, "Geometry": 2}
    (qs,) = client.post("/api/question-sets/from-bank", json={"target_marks": 20, "topics": ["algebra"]}).json()
    assert sum(q["marks"] for q in qs["questions"]) == 5  # Q3 (3) + Q4 (2)


def test_pick_to_target_is_exact_when_possible():
    import random

    class Q:
        def __init__(self, marks):
            self.marks = marks

    pool = [Q(m) for m in (7, 5, 4, 3, 2, 2, 1)]
    picked = bank_sets.pick_to_target(pool, 9, random.Random(1))
    assert sum(q.marks for q in picked) == 9


# ---------- deleting + grading ----------


def test_paper_in_use_cannot_be_deleted(client, qp_pdf, ms_pdf):
    paper = _upload(client, qp_pdf, ms_pdf)
    (qs,) = client.post("/api/question-sets/from-bank", json={"target_marks": 4}).json()
    assert client.delete(f"/api/past-papers/{paper['id']}").status_code == 409
    client.delete(f"/api/question-sets/{qs['id']}")
    assert client.delete(f"/api/past-papers/{paper['id']}").status_code == 204


def test_bank_set_can_be_submitted_and_graded(client, qp_pdf, ms_pdf, monkeypatch):
    _upload(client, qp_pdf, ms_pdf)
    (qs,) = client.post("/api/question-sets/from-bank", json={"target_marks": 10}).json()

    from app.services import deepseek_client

    seen = {}
    real_vision = deepseek_client.vision_json

    def spy(system_prompt, user_prompt, image_paths, *, mock_response):
        seen["prompt"], seen["images"] = user_prompt, image_paths
        return real_vision(system_prompt, user_prompt, image_paths, mock_response=mock_response)

    monkeypatch.setattr(deepseek_client, "vision_json", spy)
    sub = client.post(
        "/api/submissions",
        data={"question_set_id": qs["id"], "student_name": "Test"},
        files={"images": ("answer.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    ).json()
    graded = client.post(f"/api/submissions/{sub['id']}/evaluate").json()
    assert graded["evaluation"]["total_marks_possible"] == 10
    # Four mark-scheme reference images first, then the student's one photo.
    assert len(seen["images"]) == 5
    assert seen["images"][-1].name.endswith("answer.jpg")
    assert "official mark-scheme references" in seen["prompt"]
