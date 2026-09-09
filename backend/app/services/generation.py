"""
Builds the generation prompt from a Pattern + selected SourceDocuments,
calls DeepSeek, and turns the JSON response into Question rows.

The prompt asks DeepSeek to act like a CBSE paper-setter: use the supplied
past-year material as style/topic/difficulty reference, but generate NEW
questions (not verbatim copies) that satisfy the pattern's blueprint
exactly, and to include a hidden expected_answer/rubric for each question
so the evaluation step later has something to grade against.
"""
import json
import logging

from sqlalchemy.orm import Session

from .. import models
from . import deepseek_client

logger = logging.getLogger(__name__)

MAX_SOURCE_CHARS = 12000  # keep prompts a reasonable size regardless of how much is uploaded

SYSTEM_PROMPT = """You are an expert CBSE exam paper setter. You generate fresh, original \
exam questions that follow a precisely specified blueprint (sections, question types, \
marks, counts, difficulty mix), optionally inspired by reference past-year material for \
topic coverage and style — but you never copy questions verbatim from the reference text.

For every question you also produce a hidden expected_answer and a short rubric, used \
later to grade a student's photographed answer sheet. These are never shown to the student.

Always respond with a single JSON object and nothing else, matching exactly this shape:
{
  "questions": [
    {
      "section": "<section name from the blueprint, e.g. 'A'>",
      "question_type": "MCQ|VSA|SA|LA|CASE_STUDY",
      "text": "<the question text, or the full case/passage plus sub-question for CASE_STUDY>",
      "options": ["..."] or null,      // present only for MCQ, exactly 4 options
      "marks": <number, matching the section's marks_per_question>,
      "difficulty": "easy|medium|hard",
      "expected_answer": "<concise correct answer or key points>",
      "rubric": "<how to award partial marks, 1-3 sentences>"
    }
  ]
}
Produce exactly the number of questions each section's blueprint calls for, in order."""


def _build_user_prompt(pattern_config: dict, source_texts: list[str], extra_instructions: str) -> str:
    parts = [
        "Exam blueprint (JSON):",
        json.dumps(pattern_config, indent=2),
    ]
    if source_texts:
        combined = "\n\n---\n\n".join(source_texts)[:MAX_SOURCE_CHARS]
        parts.append("Reference past-year material (for topic/style/difficulty guidance only):")
        parts.append(combined)
    if extra_instructions.strip():
        parts.append(f"Additional instructions from the teacher: {extra_instructions.strip()}")
    parts.append("Now generate the question set as JSON matching the required shape.")
    return "\n\n".join(parts)


def _mock_response(pattern_config: dict) -> dict:
    """Deterministic placeholder data, shaped exactly like a real DeepSeek response,
    so the full UI flow works with zero configuration."""
    questions = []
    for section in pattern_config.get("sections", []):
        for i in range(1, section.get("num_questions", 0) + 1):
            q_type = section.get("question_type", "SA")
            entry = {
                "section": section.get("name", ""),
                "question_type": q_type,
                "text": f"[MOCK] Section {section.get('name')} Q{i}: sample {q_type} question "
                f"on {pattern_config.get('subject', 'the subject')}. "
                f"Replace with a real DEEPSEEK_API_KEY in .env to generate real questions.",
                "options": ["Option A", "Option B", "Option C", "Option D"] if q_type == "MCQ" else None,
                "marks": section.get("marks_per_question", 1),
                "difficulty": "medium",
                "expected_answer": "[MOCK] sample expected answer",
                "rubric": "[MOCK] award full marks for a correct, well-explained answer",
            }
            questions.append(entry)
    return {"questions": questions}


def generate_question_set(
    db: Session,
    *,
    pattern: models.Pattern,
    name: str,
    source_documents: list[models.SourceDocument],
    extra_instructions: str = "",
) -> models.QuestionSet:
    question_set = models.QuestionSet(
        name=name or f"{pattern.name} — generated set",
        pattern_id=pattern.id,
        subject=pattern.subject,
        grade=pattern.grade,
        status="generating",
    )
    db.add(question_set)
    db.commit()
    db.refresh(question_set)

    try:
        source_texts = [doc.extracted_text for doc in source_documents if doc.extracted_text]
        user_prompt = _build_user_prompt(pattern.config_json, source_texts, extra_instructions)
        response = deepseek_client.chat_json(
            SYSTEM_PROMPT, user_prompt, mock_response=_mock_response(pattern.config_json)
        )

        raw_questions = response.get("questions", [])
        if not raw_questions:
            raise ValueError("DeepSeek response contained no questions")

        for idx, q in enumerate(raw_questions):
            db.add(
                models.Question(
                    question_set_id=question_set.id,
                    section=str(q.get("section", "")),
                    order_index=idx,
                    question_type=str(q.get("question_type", "SA")),
                    text=str(q.get("text", "")),
                    options=q.get("options"),
                    marks=float(q.get("marks", 1) or 1),
                    difficulty=str(q.get("difficulty", "medium")),
                    expected_answer=str(q.get("expected_answer", "")),
                    rubric=str(q.get("rubric", "")),
                )
            )
        question_set.status = "ready"
    except Exception as e:  # noqa: BLE001 — record the failure on the record, don't crash the request
        logger.exception("Question set generation failed")
        question_set.status = "failed"
        question_set.error_message = str(e)

    db.commit()
    db.refresh(question_set)
    return question_set
