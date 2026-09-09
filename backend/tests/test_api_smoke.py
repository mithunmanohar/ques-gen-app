"""
End-to-end smoke test of the whole flow, run in mock mode (see conftest.py)
so it needs no DeepSeek API key and makes no network calls: create a
pattern -> generate a question set -> submit a fake answer-sheet photo ->
evaluate it -> check a graded result comes back.
"""
import io

SAMPLE_PATTERN = {
    "name": "Smoke Test Pattern",
    "subject": "Science",
    "grade": "10",
    "sections": [
        {
            "name": "A",
            "question_type": "MCQ",
            "num_questions": 2,
            "marks_per_question": 1,
        }
    ],
}


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["mock_mode"] is True


def test_pattern_crud_validates_schema(client):
    bad = client.post("/api/patterns", json={"name": "Bad", "config_json": {"sections": []}})
    assert bad.status_code == 422

    created = client.post("/api/patterns", json={"name": "Good", "config_json": SAMPLE_PATTERN})
    assert created.status_code == 200
    pattern_id = created.json()["id"]

    listed = client.get("/api/patterns")
    assert any(p["id"] == pattern_id for p in listed.json())


def test_full_generate_submit_evaluate_flow(client):
    pattern = client.post("/api/patterns", json={"name": "Flow Pattern", "config_json": SAMPLE_PATTERN}).json()

    generated = client.post(
        "/api/question-sets/generate",
        json={"pattern_id": pattern["id"], "num_sets": 1},
    )
    assert generated.status_code == 200
    question_set = generated.json()[0]
    assert question_set["status"] == "ready"
    assert len(question_set["questions"]) == 2

    answer_key = client.get(f"/api/question-sets/{question_set['id']}/answer-key").json()
    assert answer_key["questions"][0]["expected_answer"]

    fake_image = io.BytesIO(b"not-a-real-image-but-mock-mode-does-not-care")
    submission = client.post(
        "/api/submissions",
        data={"question_set_id": question_set["id"], "student_name": "Test Student"},
        files={"images": ("answer.jpg", fake_image, "image/jpeg")},
    )
    assert submission.status_code == 200
    submission_id = submission.json()["id"]

    evaluated = client.post(f"/api/submissions/{submission_id}/evaluate")
    assert evaluated.status_code == 200
    evaluation = evaluated.json()["evaluation"]
    assert evaluation is not None
    assert evaluation["is_mocked"] is True
    assert len(evaluation["items"]) == 2
    assert evaluation["total_marks_possible"] == 2
