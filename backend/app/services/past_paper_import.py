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
import time
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
    started = time.perf_counter()
    logger.info(
        "Importing past paper #%d: question paper %s (%.0f KB)%s",
        paper.id,
        paper.qp_filename,
        qp_path.stat().st_size / 1024,
        f", mark scheme {paper.ms_filename} ({ms_path.stat().st_size / 1024:.0f} KB)" if ms_path else ", no mark scheme",
    )
    try:
        logger.info("Step 1/4: finding and cropping questions")
        extraction = paper_extraction.extract_questions(qp_path)
        issues += extraction.issues
        info = extraction.info
        if info:
            paper.syllabus_code, paper.component = info.syllabus_code, info.component
            paper.session, paper.year = info.session, info.year
            duplicate = _find_duplicate(db, paper)
            if duplicate:
                logger.error("Duplicate: %s is already in the bank as paper #%d", info.label, duplicate.id)
                raise paper_extraction.ExtractionError(
                    f"{info.label} is already in the bank as '{duplicate.title}'. Delete that one first to re-import it."
                )
            if not paper.title:
                paper.title = info.label

        ms = None
        if ms_path is not None:
            logger.info("Step 2/4: reading the mark scheme")
            try:
                ms = ms_parser.parse_mark_scheme(ms_path)
            except Exception as e:  # noqa: BLE001 — a bad mark scheme shouldn't lose the questions
                logger.exception("Mark scheme parsing crashed (%s); continuing without it", type(e).__name__)
                issues.append(f"Couldn't read the mark scheme: {e}")
        if ms is not None:
            issues += ms.issues
            paper.max_mark = ms.max_mark
            if pairing_issue := _check_pairing(info, ms):
                issues.append(pairing_issue)
                logger.warning("Pairing check: %s", pairing_issue)
            else:
                logger.info("Pairing check: mark scheme matches the question paper")
        else:
            issues.append("No mark scheme — answer keys are empty and grading relies on the model's own judgement.")
            logger.info("Step 2/4: skipped — no mark scheme uploaded")

        logger.info("Step 3/4: rendering question images and running checks")

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
                    logger.debug(
                        "  Q%d mark scheme: %s (marks column total %s)",
                        q.number,
                        ", ".join(r.label for r in rows),
                        ms_total if ms_total is not None else "not numeric",
                    )
                else:
                    flags.append("No mark scheme entry found for this question.")
            for flag in flags[len(q.flags):]:
                logger.warning("Q%d check: %s", q.number, flag)

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
                logger.warning("Orphan check: mark scheme answers for missing question(s) %s", orphans)
            if ms.max_mark is not None and total != ms.max_mark:
                issues.append(f"Question marks add up to {total}, but the mark scheme's maximum is {ms.max_mark}.")
                logger.warning("Total check: questions add up to %d, mark scheme maximum is %d", total, ms.max_mark)
            elif ms.max_mark is not None:
                logger.info("Total check: questions add up to %d = mark scheme maximum", total)

        logger.info("Step 4/4: tagging topics")
        try:
            tags = topic_tagging.tag_topics(
                paper.subject, paper.paper_code, [(q.number, q.text) for q in extraction.questions]
            )
            for bq in paper.questions:
                bq.topics = tags.get(bq.number, [])
            tagged = sum(1 for bq in paper.questions if bq.topics)
            logger.info("Topics tagged on %d of %d question(s)", tagged, len(paper.questions))
        except Exception as e:  # noqa: BLE001 — topics are optional
            logger.exception("Topic tagging failed (%s); questions stay untagged", type(e).__name__)
            issues.append(f"Topic tagging failed, so questions are untagged: {e}")

        paper.status = "ready"
        logger.info(
            "Import finished in %.1fs: %d question(s), %d marks, %d flagged, %d paper warning(s)",
            time.perf_counter() - started,
            len(paper.questions),
            sum(q.marks for q in paper.questions),
            sum(1 for q in paper.questions if q.flags),
            len(issues),
        )
    except paper_extraction.ExtractionError as e:
        logger.error("Import failed: %s", e)
        paper.status = "failed"
        paper.questions.clear()
        issues.append(str(e))
    except Exception as e:  # noqa: BLE001 — record the failure on the paper, don't crash the request
        logger.exception("Import crashed with %s: %s", type(e).__name__, e)
        paper.status = "failed"
        paper.questions.clear()
        issues.append(f"Extraction failed ({type(e).__name__}): {e}. See the processing log for the full traceback.")

    paper.issues = issues
    db.commit()
    db.refresh(paper)
    return paper
