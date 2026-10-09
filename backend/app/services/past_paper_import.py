"""
Imports an uploaded Cambridge question paper (+ optional mark scheme) into the
question bank, fully automatically:

  1. extract one cropped image per question (paper_extraction)
  2. parse the mark scheme into per-question answer rows + row images (mark_scheme)
  3. run automatic checks — they never block the import, they attach warnings:
       paper level:    numbering gaps, marks total vs the mark scheme's maximum,
                       mark-scheme answers with no matching question, QP/MS mismatch
       question level: no [n] marks found, no mark-scheme entry, marks disagree
                       with the mark scheme, unusually long (3+ page) crop
  4. tag topics with DeepSeek (best-effort)

Flagged questions are still stored; set generation skips them unless asked not to.
"""
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from .. import models
from . import mark_scheme as ms_parser
from . import paper_extraction, topic_tagging

logger = logging.getLogger(__name__)


def _same_session(a: str | None, b: str | None) -> bool:
    return not a or not b or a[:3].lower() == b[:3].lower()


def _check_pairing(info: paper_extraction.PaperInfo | None, ms: ms_parser.MarkSchemeResult) -> str | None:
    if info is None or not ms.syllabus_code:
        return None
    if (ms.syllabus_code, ms.component) != (info.syllabus_code, info.component) or not _same_session(
        ms.session, info.session
    ) or (ms.year and ms.year != info.year):
        ms_label = f"{ms.syllabus_code}/{ms.component} {ms.session or ''} {ms.year or ''}".strip()
        return f"The mark scheme looks like it's for {ms_label}, not {info.label} — check you uploaded the matching pair."
    return None


def _find_duplicate(db: Session, paper: models.PastPaper) -> models.PastPaper | None:
    return (
        db.query(models.PastPaper)
        .filter(
            models.PastPaper.id != paper.id,
            models.PastPaper.status == "ready",
            models.PastPaper.syllabus_code == paper.syllabus_code,
            models.PastPaper.component == paper.component,
            models.PastPaper.session == paper.session,
            models.PastPaper.year == paper.year,
        )
        .first()
    )


def import_past_paper(db: Session, paper: models.PastPaper, qp_path: Path, ms_path: Path | None) -> models.PastPaper:
    out_dir = Path(paper.storage_dir)
    issues: list[str] = []
    try:
        extraction = paper_extraction.extract_questions(qp_path)
        issues += extraction.issues
        info = extraction.info
        if info:
            paper.syllabus_code, paper.component = info.syllabus_code, info.component
            paper.session, paper.year = info.session, info.year
            duplicate = _find_duplicate(db, paper)
            if duplicate:
                raise paper_extraction.ExtractionError(
                    f"{info.label} is already in the bank as '{duplicate.title}'. Delete that one first to re-import it."
                )
            if not paper.title:
                paper.title = info.label

        ms = None
        if ms_path is not None:
            try:
                ms = ms_parser.parse_mark_scheme(ms_path)
            except Exception as e:  # noqa: BLE001 — a bad mark scheme shouldn't lose the questions
                logger.exception("Mark scheme parsing failed")
                issues.append(f"Couldn't read the mark scheme: {e}")
        if ms is not None:
            issues += ms.issues
            paper.max_mark = ms.max_mark
            if pairing_issue := _check_pairing(info, ms):
                issues.append(pairing_issue)
        else:
            issues.append("No mark scheme — answer keys are empty and grading relies on the model's own judgement.")

        for q in extraction.questions:
            flags = list(q.flags)
            image_path = ""
            if q.segments:
                image_path = str(out_dir / f"q{q.number:02d}.png")
                paper_extraction.render_segments(qp_path, q.segments, Path(image_path))

            ms_entries: list[dict] = []
            ms_image_path = ""
            if ms is not None:
                rows = ms.rows_for(q.number)
                if rows:
                    ms_entries = [
                        {"label": r.label, "answer": r.answer, "marks": r.marks, "partial_marks": r.partial_marks}
                        for r in rows
                    ]
                    ms_image_path = str(out_dir / f"ms{q.number:02d}.png")
                    paper_extraction.render_segments(
                        ms_path, ms_parser.question_segments(ms, q.number), Path(ms_image_path)
                    )
                    ms_total = ms_parser.numeric_marks(rows)
                    if ms_total is not None and ms_total != q.marks:
                        flags.append(f"Question shows {q.marks} marks but the mark scheme awards {ms_total}.")
                else:
                    flags.append("No mark scheme entry found for this question.")

            paper.questions.append(
                models.BankQuestion(
                    number=q.number,
                    text=q.text,
                    marks=q.marks,
                    subparts=q.subparts,
                    flags=flags,
                    image_path=image_path,
                    ms_entries=ms_entries,
                    ms_image_path=ms_image_path,
                )
            )

        total = sum(q.marks for q in extraction.questions)
        if ms is not None:
            found = {q.number for q in extraction.questions}
            orphans = sorted({r.question for r in ms.rows} - found)
            if orphans:
                issues.append(
                    "The mark scheme has answers for question(s) "
                    f"{', '.join(map(str, orphans))} that weren't found in the question paper."
                )
            if ms.max_mark is not None and total != ms.max_mark:
                issues.append(f"Question marks add up to {total}, but the mark scheme's maximum is {ms.max_mark}.")

        try:
            tags = topic_tagging.tag_topics(
                paper.subject, paper.paper_code, [(q.number, q.text) for q in extraction.questions]
            )
            for bq in paper.questions:
                bq.topics = tags.get(bq.number, [])
        except Exception as e:  # noqa: BLE001 — topics are optional
            logger.exception("Topic tagging failed")
            issues.append(f"Topic tagging failed, so questions are untagged: {e}")

        paper.status = "ready"
    except paper_extraction.ExtractionError as e:
        paper.status = "failed"
        paper.questions.clear()
        issues.append(str(e))
    except Exception as e:  # noqa: BLE001 — record the failure on the paper, don't crash the request
        logger.exception("Past paper import failed")
        paper.status = "failed"
        paper.questions.clear()
        issues.append(f"Extraction failed: {e}")

    paper.issues = issues
    db.commit()
    db.refresh(paper)
    return paper
