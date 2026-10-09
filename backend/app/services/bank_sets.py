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
import random

from sqlalchemy.orm import Session

from .. import models

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
    wanted = {t.strip().lower() for t in topics if t.strip()}
    if wanted:
        pool = [q for q in pool if wanted & {t.lower() for t in q.topics}]
    if not include_flagged:
        pool = [q for q in pool if not q.flags]
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
    pool = candidate_questions(
        db, past_paper_ids=past_paper_ids, topics=topics, include_flagged=include_flagged, avoid_used=avoid_used
    )
    if not pool:
        raise BankSelectionError(
            "No bank questions match these filters. Upload more papers, widen the topic/paper choice, "
            "or allow flagged / previously used questions."
        )

    rng = random.Random(seed)
    results = []
    for i in range(num_sets):
        picked = pick_to_target(pool, target_marks, rng)
        picked_ids = {q.id for q in picked}
        pool = [q for q in pool if q.id not in picked_ids]
        picked.sort(key=lambda q: (q.number, q.past_paper_id))
        total = sum(q.marks for q in picked)

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
        results.append(question_set)
    return results
