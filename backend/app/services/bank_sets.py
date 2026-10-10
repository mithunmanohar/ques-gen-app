"""
Builds new question sets by picking real past-paper questions from the bank,
as the alternative to AI generation.

Selection: filter the bank (papers, topics, flagged, already-used), then pick
at random until the marks target is reached. Several random orderings are
tried and the closest total that doesn't exceed the target wins, so small
targets usually land exactly. Sets made in one request never share a question.
Picked questions are printed in their original question-number order, which
on Cambridge papers runs roughly easy to hard.
"""
import logging
import random

from sqlalchemy.orm import Session

from .. import models
from ..logging_setup import capture_operation_log

logger = logging.getLogger(__name__)

SHUFFLE_ATTEMPTS = 60


class BankSelectionError(ValueError):
    pass


def candidate_questions(
    db: Session,
    *,
    past_paper_ids: list[int],
    topics: list[str],
    include_flagged: bool,
    avoid_used: bool,
) -> list[models.BankQuestion]:
    query = (
        db.query(models.BankQuestion)
        .join(models.PastPaper)
        .filter(models.PastPaper.status == "ready", models.BankQuestion.image_path != "")
    )
    if past_paper_ids:
        query = query.filter(models.BankQuestion.past_paper_id.in_(past_paper_ids))
    if avoid_used:
        used = db.query(models.Question.bank_question_id).filter(models.Question.bank_question_id.isnot(None))
        query = query.filter(models.BankQuestion.id.notin_(used))
    pool = query.all()
    logger.info(
        "Bank questions from %s%s: %d",
        f"paper(s) {past_paper_ids}" if past_paper_ids else "all ready papers",
        ", excluding ones already used in a set" if avoid_used else "",
        len(pool),
    )
    wanted = {t.strip().lower() for t in topics if t.strip()}
    if wanted:
        pool = [q for q in pool if wanted & {t.lower() for t in q.topics}]
        logger.info("After topic filter %s: %d", sorted(wanted), len(pool))
    if not include_flagged:
        flagged = sum(1 for q in pool if q.flags)
        pool = [q for q in pool if not q.flags]
        logger.info("After leaving out %d flagged question(s): %d", flagged, len(pool))
    zero = sum(1 for q in pool if q.marks <= 0)
    if zero:
        logger.info("Leaving out %d question(s) with no marks", zero)
    return [q for q in pool if q.marks > 0]


def pick_to_target(pool: list[models.BankQuestion], target: float, rng: random.Random) -> list[models.BankQuestion]:
    best: list[models.BankQuestion] = []
    best_total = 0.0
    for _ in range(SHUFFLE_ATTEMPTS):
        order = pool[:]
        rng.shuffle(order)
        picked, total = [], 0.0
        for q in order:
            if total + q.marks <= target:
                picked.append(q)
                total += q.marks
                if total == target:
                    break
        if total > best_total:
            best, best_total = picked, total
        if best_total == target:
            break
    return best


def _expected_answer(entries: list[dict]) -> str:
    return "\n".join(f"{e['label']}: {e['answer']}" + (f"  [{e['marks']}]" if e.get("marks") else "") for e in entries)


def _rubric(entries: list[dict]) -> str:
    return "\n".join(f"{e['label']}: {e['partial_marks']}" for e in entries if e.get("partial_marks"))


def build_bank_sets(
    db: Session,
    *,
    name: str,
    num_sets: int,
    target_marks: float,
    past_paper_ids: list[int],
    topics: list[str],
    include_flagged: bool,
    avoid_used: bool,
    seed: int | None = None,
) -> list[models.QuestionSet]:
    with capture_operation_log() as shared_lines:
        pool = candidate_questions(
            db, past_paper_ids=past_paper_ids, topics=topics, include_flagged=include_flagged, avoid_used=avoid_used
        )
        if not pool:
            logger.warning("No bank questions match the filters; nothing to build")
            raise BankSelectionError(
                "No bank questions match these filters. Upload more papers, widen the topic/paper choice, "
                "or allow flagged / previously used questions."
            )
        logger.info(
            "Building %d set(s) of %g marks from a pool of %d question(s) worth %g marks",
            num_sets,
            target_marks,
            len(pool),
            sum(q.marks for q in pool),
        )

    rng = random.Random(seed)
    results = []
    for i in range(num_sets):
        with capture_operation_log() as set_lines:
            picked = pick_to_target(pool, target_marks, rng)
            picked_ids = {q.id for q in picked}
            pool = [q for q in pool if q.id not in picked_ids]
            picked.sort(key=lambda q: (q.number, q.past_paper_id))
            total = sum(q.marks for q in picked)
            logger.info(
                "Set %d: picked %d question(s) worth %g marks: %s",
                i + 1,
                len(picked),
                total,
                ", ".join(f"{q.source_label} ({q.marks:g})" for q in picked) or "none",
            )

            set_name = name or f"Past-paper practice ({total:g} marks)"
            if num_sets > 1:
                set_name = f"{set_name} — Set {i + 1}"
            subjects = list(dict.fromkeys(q.past_paper.subject for q in picked if q.past_paper.subject))
            question_set = models.QuestionSet(
                name=set_name,
                pattern_id=None,
                source="bank",
                subject=", ".join(subjects),
                status="ready" if picked else "failed",
            )
            if not picked:
                question_set.error_message = "Ran out of matching bank questions for this set."
            elif total < target_marks:
                question_set.error_message = (
                    f"Reached {total:g} of the {target_marks:g} marks asked for — not enough matching questions."
                )
            if question_set.error_message:
                logger.warning("Set %d: %s", i + 1, question_set.error_message)
        question_set.processing_log = shared_lines + set_lines
        db.add(question_set)
        for idx, q in enumerate(picked):
            question_set.questions.append(
                models.Question(
                    section="",
                    order_index=idx,
                    question_type="PAST_PAPER",
                    text=q.text,
                    options=None,
                    marks=q.marks,
                    difficulty="",
                    expected_answer=_expected_answer(q.ms_entries),
                    rubric=_rubric(q.ms_entries),
                    bank_question_id=q.id,
                )
            )
        db.commit()
        db.refresh(question_set)
        logger.info("Saved question set #%d '%s'", question_set.id, question_set.name)
        results.append(question_set)
    return results
