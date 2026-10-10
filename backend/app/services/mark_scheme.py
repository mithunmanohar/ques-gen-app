"""
Parses a Cambridge (CAIE) mark scheme PDF into per-question answer entries.

The answer table (Question | Answer | Marks | Partial Marks) is ruled, so the
column boundaries come from its vertical rules and each row starts at a label
in the Question column such as "4", "8(a)" or "11(a)(i)". A row runs until the
next label; rows (or row overflow) that continue at the top of the next page
are carried over.

Two outputs per row: the cell text, and the row's region on the page. The text
layer scrambles stacked maths (fractions come out as stray digits), so the
region is rendered as an image too and that image is what graders should trust.
"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .paper_extraction import FOOTER_ZONE, Segment, clean_text

logger = logging.getLogger(__name__)

LABEL_RE = re.compile(r"^\s*(\d{1,2})((?:\([a-z]{1,4}\))*)\s*$")
MAX_MARK_RE = re.compile(r"Maximum\s+Mark:?\s*(\d+)", re.IGNORECASE)
MS_CODE_RE = re.compile(r"\b(\d{4})/(\d{2})\b")
MS_SESSION_RE = re.compile(r"\b(May/June|Oct(?:ober)?/Nov(?:ember)?|Feb(?:ruary)?/March)\s+(\d{4})\b")
HEADER_WORDS = ("Question", "Answer", "Marks")


@dataclass
class MarkSchemeRow:
    label: str  # "11(a)(i)"
    question: int
    answer: str = ""
    marks: str = ""
    partial_marks: str = ""
    segments: list[Segment] = field(default_factory=list)


@dataclass
class MarkSchemeResult:
    max_mark: int | None
    syllabus_code: str | None
    component: str | None
    session: str | None
    year: str | None
    rows: list[MarkSchemeRow]
    header: Segment | None
    issues: list[str]

    def rows_for(self, question: int) -> list[MarkSchemeRow]:
        return [r for r in self.rows if r.question == question]


@dataclass
class _Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


def _words(page: pymupdf.Page) -> list[_Word]:
    # Words, not lines: one PDF text line often runs across the Marks and Partial Marks columns.
    return [_Word(*w[:4], w[4]) for w in page.get_text("words") if w[4].strip()]


def _header_line(page: pymupdf.Page) -> pymupdf.Rect | None:
    words = page.get_text("words")
    for w in words:
        if w[4] != "Question":
            continue
        same_row = {x[4] for x in words if abs(x[1] - w[1]) < 3}
        if all(h in same_row for h in HEADER_WORDS):
            row = [x for x in words if abs(x[1] - w[1]) < 3]
            return pymupdf.Rect(min(x[0] for x in row), min(x[1] for x in row), max(x[2] for x in row), max(x[3] for x in row))
    return None


def _column_rules(page: pymupdf.Page, table_top: float) -> list[float]:
    """x positions of the table's vertical rules (outer edges included), left to right."""
    heights: dict[int, float] = {}
    for d in page.get_drawings():
        r = d["rect"]
        if r.width < 1.5 and r.height > 4 and r.y1 > table_top:
            heights[round(r.x0)] = heights.get(round(r.x0), 0) + r.height
    if not heights:
        return []
    tallest = max(heights.values())
    xs = sorted(x for x, h in heights.items() if h >= tallest * 0.5)
    merged: list[float] = []
    for x in xs:
        if not merged or x - merged[-1] > 3:
            merged.append(float(x))
    return merged


def _row_separators(page: pymupdf.Page) -> list[float]:
    return sorted({round(d["rect"].y0, 1) for d in page.get_drawings() if d["rect"].height < 1.5 and d["rect"].width > 15})


def _column_of(x_center: float, rules: list[float]) -> int:
    for i in range(len(rules) - 1):
        if rules[i] <= x_center < rules[i + 1]:
            return i
    return -1


def _cells(words: list[_Word], rules: list[float], y0: float, y1: float) -> list[str]:
    cols: list[list[_Word]] = [[] for _ in range(max(len(rules) - 1, 0))]
    for w in words:
        if y0 <= w.yc < y1:
            c = _column_of(w.xc, rules)
            if c >= 0:
                cols[c].append(w)
    return [
        clean_text(" ".join(w.text for w in sorted(col, key=lambda w: (round(w.y0 / 4), w.x0))))
        for col in cols
    ]


def _assign_cells(row: MarkSchemeRow, cells: list[str]) -> None:
    def add(existing: str, more: str) -> str:
        return f"{existing} {more}".strip() if more else existing

    if len(cells) >= 2:
        row.answer = add(row.answer, cells[1])
    if len(cells) >= 3:
        row.marks = add(row.marks, cells[2])
    if len(cells) >= 4:
        row.partial_marks = add(row.partial_marks, " ".join(cells[3:]))


def parse_mark_scheme(pdf_path: Path) -> MarkSchemeResult:
    doc = pymupdf.open(pdf_path)
    try:
        first_text = doc[0].get_text() if len(doc) else ""
        m = MAX_MARK_RE.search(first_text)
        max_mark = int(m.group(1)) if m else None
        code = MS_CODE_RE.search(first_text)
        session = MS_SESSION_RE.search(first_text)
        logger.info(
            "Opened mark scheme %s: %d page(s); code %s, session %s, maximum mark %s",
            pdf_path.name,
            len(doc),
            f"{code.group(1)}/{code.group(2)}" if code else "not found",
            f"{session.group(1)} {session.group(2)}" if session else "not found",
            max_mark if max_mark is not None else "not found",
        )

        rows: list[MarkSchemeRow] = []
        header: Segment | None = None
        issues: list[str] = []
        for pno, page in enumerate(doc):
            head = _header_line(page)
            if head is None:
                logger.debug("  mark scheme page %d: no answer table (cover/instructions page)", pno + 1)
                continue
            rules = _column_rules(page, head.y1)
            if len(rules) < 4:
                issues.append(f"Mark scheme page {pno + 1}: couldn't find the table's column rules; page skipped.")
                logger.warning("Mark scheme page %d: only %d vertical rule(s) found (need 4+); page skipped", pno + 1, len(rules))
                continue
            seps = _row_separators(page)
            table_top = min((s for s in seps if s > head.y1), default=head.y1 + 2)
            footer_top = page.rect.height - FOOTER_ZONE
            table_bottom = max((s for s in seps if s < footer_top), default=footer_top)
            x0, x1 = rules[0] - 1, rules[-1] + 1
            if header is None:
                header_top = max((s for s in seps if s < head.y0), default=head.y0 - 4)
                header = Segment(pno, pymupdf.Rect(x0, header_top - 1, x1, table_top + 1))

            words = [w for w in _words(page) if table_top <= w.y0 and w.y1 <= table_bottom + 2]
            starts = []
            for w in words:
                lm = LABEL_RE.match(w.text)
                if lm and _column_of(w.xc, rules) == 0:
                    top = max((s for s in seps if s <= w.y0 + 1), default=w.y0 - 4)
                    starts.append((top, lm.group(1) + lm.group(2), int(lm.group(1))))
            starts.sort()

            # Overflow of the previous page's last row, above this page's first label.
            first_top = starts[0][0] if starts else table_bottom
            if rows and first_top - table_top > 4:
                carried = _cells(words, rules, table_top, first_top)
                if any(carried[1:]):
                    logger.info("  mark scheme page %d: row %s continues from the previous page", pno + 1, rows[-1].label)
                    _assign_cells(rows[-1], carried)
                    rows[-1].segments.append(Segment(pno, pymupdf.Rect(x0, table_top - 1, x1, first_top + 1)))

            for i, (top, label, qnum) in enumerate(starts):
                bottom = starts[i + 1][0] if i + 1 < len(starts) else table_bottom
                row = MarkSchemeRow(label=label, question=qnum)
                _assign_cells(row, _cells(words, rules, top, bottom))
                row.segments.append(Segment(pno, pymupdf.Rect(x0, top - 1, x1, bottom + 1)))
                rows.append(row)
                logger.debug(
                    "  row %s: answer=%r marks=%r partial=%r", label, row.answer[:60], row.marks, row.partial_marks[:60]
                )
            logger.info(
                "Mark scheme page %d: %d column(s), %d answer row(s)%s",
                pno + 1,
                len(rules) - 1,
                len(starts),
                f" ({starts[0][1]} … {starts[-1][1]})" if starts else "",
            )

        if not rows:
            issues.append("No answer rows found in the mark scheme (expected a Question | Answer | Marks table).")
        logger.info(
            "Mark scheme parsed: %d row(s) covering %d question(s)", len(rows), len({r.question for r in rows})
        )
        for issue in issues:
            logger.warning("Mark scheme check: %s", issue)
        return MarkSchemeResult(
            max_mark=max_mark,
            syllabus_code=code.group(1) if code else None,
            component=code.group(2) if code else None,
            session=session.group(1) if session else None,
            year=session.group(2) if session else None,
            rows=rows,
            header=header,
            issues=issues,
        )
    finally:
        doc.close()


def question_segments(result: MarkSchemeResult, question: int) -> list[Segment]:
    """The table header plus every row region for one question, with touching regions merged."""
    merged: list[Segment] = []
    for row in result.rows_for(question):
        for seg in row.segments:
            last = merged[-1] if merged else None
            if last and last.page == seg.page and abs(last.rect.y1 - seg.rect.y0) <= 3:
                last.rect = pymupdf.Rect(last.rect.x0, last.rect.y0, last.rect.x1, seg.rect.y1)
            else:
                merged.append(Segment(seg.page, pymupdf.Rect(seg.rect)))
    if merged and result.header is not None:
        merged.insert(0, Segment(result.header.page, pymupdf.Rect(result.header.rect)))
    return merged


MARK_TOKEN_RE = re.compile(r"^(?:(\d{1,2})(?:FT)?|[MAB](\d))$")


def numeric_marks(rows: list[MarkSchemeRow]) -> int | None:
    """Total marks from the Marks column ('2', '2 2', 'M1 A1', '2 B1'); None if any token is something else."""
    total = 0
    tokens = [t for r in rows for t in r.marks.split()]
    if not tokens:
        return None
    for t in tokens:
        m = MARK_TOKEN_RE.match(t)
        if not m:
            return None
        total += int(m.group(1) or m.group(2))
    return total
