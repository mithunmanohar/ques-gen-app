"""
Exercises the count-enforcement retry loop in generation.py directly
(bypassing mock mode's own auto-matching mock data) by stubbing out
deepseek_client.chat_json to return controlled, possibly-mismatched
responses across successive calls.
"""
from app import models
from app.db import SessionLocal
from app.services import generation

PATTERN_CONFIG = {
    "name": "Retry Test Pattern",
    "sections": [
        {"name": "A", "question_type": "MCQ", "num_questions": 2, "marks_per_question": 1},
    ],
}


def _question(section="A", **overrides):
    q = {
        "section": section,
        "question_type": "MCQ",
        "text": "sample",
        "options": ["a", "b", "c", "d"],
        "marks": 1,
        "difficulty": "easy",
        "expected_answer": "a",
        "rubric": "full marks for a",
    }
    q.update(overrides)
    return q


def _make_pattern(db) -> models.Pattern:
    pattern = models.Pattern(name="Retry Test Pattern", subject="Science", grade="10", config_json=PATTERN_CONFIG)
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return pattern


def test_generation_succeeds_after_one_retry(client, monkeypatch):
    # First call returns only 1 of the 2 required questions; second call is exact.
    responses = [
        {"questions": [_question()]},
        {"questions": [_question(), _question()]},
    ]

    def fake_chat_json(system_prompt, user_prompt, *, mock_response):
        return responses.pop(0)

    monkeypatch.setattr(generation.deepseek_client, "chat_json", fake_chat_json)

    db = SessionLocal()
    try:
        pattern = _make_pattern(db)
        question_set = generation.generate_question_set(
            db, pattern=pattern, name="Retry Set", source_documents=[]
        )
        assert question_set.status == "ready"
        assert len(question_set.questions) == 2
    finally:
        db.close()


def test_generation_fails_after_persistent_mismatch(client, monkeypatch):
    def fake_chat_json(system_prompt, user_prompt, *, mock_response):
        return {"questions": [_question()]}  # always short by one

    monkeypatch.setattr(generation.deepseek_client, "chat_json", fake_chat_json)

    db = SessionLocal()
    try:
        pattern = _make_pattern(db)
        question_set = generation.generate_question_set(
            db, pattern=pattern, name="Failing Set", source_documents=[]
        )
        assert question_set.status == "failed"
        assert "expected 2, got 1" in question_set.error_message
        assert len(question_set.questions) == 0
    finally:
        db.close()
