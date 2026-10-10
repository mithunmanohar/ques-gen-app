"""
Grades a Submission: sends the photographed answer sheet image(s) straight
to DeepSeek's vision model together with the question set (and its hidden
expected_answer/rubric), and asks it to read the handwriting, match each
answer to a question, and grade it — no separate OCR step.

If DeepSeek's vision output turns out to be unreliable on messy
handwriting, a local-OCR-then-text-grade pipeline can be slotted in here
later (chat_json in deepseek_client.py already supports that path) without
touching routers or models.
"""
import json
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from .. import models
from ..logging_setup import capture_operation_log
from . import deepseek_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are grading a student's handwritten exam answer sheet, photographed \
and provided to you as image(s). You are also given the original question paper with, for \
each question, its marks and a hidden expected_answer/rubric (never shown to the student).

For each question:
  - Find the student's answer in the image(s) (it may span any part of any page; answers
    are not necessarily in question order).
  - Judge correctness against the expected_answer and rubric, awarding partial marks per
    the rubric where reasonable, and 0 if the question was left unattempted.
  - If the answer is genuinely illegible, award 0 and say so in the feedback rather than
    guessing.

Respond with a single JSON object and nothing else, matching exactly this shape:
{
  "overall_feedback": "<2-4 sentences of overall feedback for the student>",
  "items": [
    {
      "question_order_index": <integer, matching the order_index given for that question>,
      "extracted_answer": "<what the student wrote, transcribed/summarized>",
      "marks_awarded": <number>,
      "marks_possible": <number, matching that question's marks>,
      "is_correct": <true if full marks awarded, else false>,
      "feedback": "<1-2 sentences specific to this answer>"
    }
  ]
}
Include exactly one item per question in the question paper, in any order.

Some questions come from official Cambridge past papers (question_type "PAST_PAPER"). For \
those, expected_answer and rubric are the official mark scheme: follow its mark codes \
(M = method mark, A = accuracy mark, dependent on the M mark, B = independent mark, \
FT = follow-through from the student's earlier answer, oe = or equivalent, cao = correct \
answer only, nfww = not from wrong working). Their text was extracted from a PDF, so maths \
in it may be garbled; an image of the official mark-scheme rows may also be attached as a \
reference image — trust that image over the extracted text. Reference images are never \
student work."""


def _question_payload(question: models.Question) -> dict:
    return {
        "order_index": question.order_index,
        "section": question.section,
        "question_type": question.question_type,
        "marks": question.marks,
        "text": question.text,
        "options": question.options,
        "expected_answer": question.expected_answer,
        "rubric": question.rubric,
    }


def _reference_images(questions: list[models.Question]) -> list[tuple[int, Path]]:
    """(order_index, path) of the official mark-scheme image for each past-paper question that has one."""
    refs = []
    for q in questions:
        if q.bank_question and q.bank_question.ms_image_path and Path(q.bank_question.ms_image_path).is_file():
            refs.append((q.order_index, Path(q.bank_question.ms_image_path)))
    return refs


def _build_user_prompt(questions: list[models.Question], references: list[tuple[int, Path]] | None = None) -> str:
    payload = [_question_payload(q) for q in questions]
    references = references or []
    if references:
        listing = ", ".join(f"image {i + 1} = mark scheme for order_index {idx}" for i, (idx, _) in enumerate(references))
        images_note = (
            f"\n\nThe first {len(references)} attached image(s) are official mark-scheme references ({listing}). "
            "The remaining attached image(s) are the student's photographed answer sheet. "
        )
    else:
        images_note = "\n\nThe attached image(s) are the student's photographed answer sheet. "
    return (
        "Question paper with hidden answer key (JSON):\n"
        + json.dumps(payload, indent=2)
        + images_note
        + "Grade it now and respond with the required JSON."
    )


def _mock_response(questions: list[models.Question]) -> dict:
    items = []
    for q in questions:
        items.append(
            {
                "question_order_index": q.order_index,
                "extracted_answer": "[MOCK] could not read image — no DEEPSEEK_API_KEY configured",
                "marks_awarded": 0,
                "marks_possible": q.marks,
                "is_correct": False,
                "feedback": "[MOCK] set DEEPSEEK_API_KEY in .env to get real grading.",
            }
        )
    return {
        "overall_feedback": "[MOCK] This is placeholder feedback. Configure DEEPSEEK_API_KEY in .env "
        "to grade real answer sheets.",
        "items": items,
    }


def evaluate_submission(db: Session, submission: models.Submission) -> models.Evaluation:
    with capture_operation_log() as log_lines:
        try:
            return _evaluate(db, submission)
        finally:
            submission.processing_log = list(log_lines)
            db.commit()


def _evaluate(db: Session, submission: models.Submission) -> models.Evaluation:
    logger.info("Grading submission #%d for question set #%d", submission.id, submission.question_set_id)
    submission.status = "evaluating"
    submission.error_message = ""
    db.commit()

    questions = (
        db.query(models.Question)
        .filter(models.Question.question_set_id == submission.question_set_id)
        .order_by(models.Question.order_index)
        .all()
    )
    image_paths = [Path(img.file_path) for img in submission.images]
    logger.info(
        "%d question(s) worth %g marks; %d answer-sheet photo(s): %s",
        len(questions),
        sum(q.marks for q in questions),
        len(image_paths),
        ", ".join(f"{p.name} ({p.stat().st_size / 1024:.0f} KB)" if p.is_file() else f"{p.name} (MISSING)" for p in image_paths),
    )
    missing = [p.name for p in image_paths if not p.is_file()]
    if missing:
        logger.error("Answer-sheet photo file(s) missing on disk: %s", ", ".join(missing))

    settings_mock = False
    try:
        from ..config import get_settings

        settings_mock = get_settings().effective_mock_mode

        references = _reference_images(questions)
        if references:
            logger.info("Attaching %d official mark-scheme image(s) as grading references", len(references))
        user_prompt = _build_user_prompt(questions, references)
        response = deepseek_client.vision_json(
            SYSTEM_PROMPT,
            user_prompt,
            [path for _, path in references] + image_paths,
            mock_response=_mock_response(questions),
        )

        by_order_index = {q.order_index: q for q in questions}
        evaluation = models.Evaluation(submission_id=submission.id, is_mocked=settings_mock)
        db.add(evaluation)
        db.flush()

        total_awarded = 0.0
        total_possible = 0.0
        items = response.get("items", [])
        logger.info("Grader returned %d item(s) for %d question(s)", len(items), len(questions))
        for item in items:
            question = by_order_index.get(item.get("question_order_index"))
            if question is None:
                logger.warning("Ignoring graded item for unknown question_order_index %r", item.get("question_order_index"))
                continue
            marks_awarded = float(item.get("marks_awarded", 0) or 0)
            marks_possible = float(item.get("marks_possible", question.marks) or question.marks)
            total_awarded += marks_awarded
            total_possible += marks_possible
            db.add(
                models.EvaluationItem(
                    evaluation_id=evaluation.id,
                    question_id=question.id,
                    extracted_answer=str(item.get("extracted_answer", "")),
                    marks_awarded=marks_awarded,
                    marks_possible=marks_possible,
                    is_correct=bool(item.get("is_correct", False)),
                    feedback=str(item.get("feedback", "")),
                )
            )
            logger.info("  Q%d: %g / %g", question.order_index + 1, marks_awarded, marks_possible)
        ungraded = set(by_order_index) - {item.get("question_order_index") for item in items}
        if ungraded:
            logger.warning(
                "No grade returned for question(s) %s — they count as 0", ", ".join(str(i + 1) for i in sorted(ungraded))
            )

        evaluation.total_marks_awarded = total_awarded
        evaluation.total_marks_possible = total_possible or sum(q.marks for q in questions)
        evaluation.overall_feedback = str(response.get("overall_feedback", ""))
        submission.status = "evaluated"
        logger.info(
            "Graded: %g / %g%s", evaluation.total_marks_awarded, evaluation.total_marks_possible, " (mock)" if settings_mock else ""
        )

    except Exception as e:  # noqa: BLE001
        logger.exception("Grading failed: %s: %s", type(e).__name__, e)
        submission.status = "failed"
        submission.error_message = f"{type(e).__name__}: {e}"
        db.commit()
        raise

    db.commit()
    db.refresh(evaluation)
    return evaluation
