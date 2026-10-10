"""
Splits a born-digital Cambridge (CAIE) question paper PDF into one image per
question, without OCR or AI.

How it works:
  - Question numbers are bold text at a fixed left-margin x position. Every
    bold "1".."99" that starts a line is a candidate; candidates are grouped
    by x position, and the group whose numbers run 1, 2, 3, ... the longest
    wins. That drops cover-page barcode digits, axis labels, table cells etc.
  - A question runs from its number to the next question's number. Its crop
    is the union of the real content (text lines + vector drawings) in that
    range, so the blank answer/working space after its last line is left out.
  - Headers, footers and notes like "Questions 21 and 22 are printed on the
    next page" are ignored. A question that continues onto later pages gets
    one segment per page; the segments are stitched into a single image.
  - Every crop of a paper uses the same x range, so printed questions all
    come out at the same scale. The original question number is whited out
    so a new paper can renumber it.
"""
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

HEADER_ZONE = 55  # pt from the top of the page: page number
FOOTER_ZONE = 50  # pt from the bottom: syllabus code, copyright, "Turn over"
PAD = 4
RENDER_SCALE = 2.5  # 180 dpi — sharp enough to print
SEGMENT_GAP = 6
OWNER_MARGIN = 12  # content ending within this distance above a question number belongs to that question

PAPER_CODE_RE = re.compile(r"\b(\d{4})/(\d{2})/([A-Z])/([A-Z])/(\d{2})\b")
QNUM_RE = re.compile(r"^\s*(\d{1,2})(?=\s|$)")
MARKS_RE = re.compile(r"\[(\d{1,2})\]")
SUBPART_RE = re.compile(r"^\s*(?:\d{1,2}\s+)?\(([a-h])\)")
BOILERPLATE_RE = re.compile(
    r"BLANK PAGE|printed on the next page|^\s*\[?Turn over|©\s*UCLES|"
    r"Permission to reproduce items|Cambridge Assessment International Education is part of|"
    r"To avoid the issue of disclosure|DO NOT WRITE IN THIS MARGIN|"
    r"^\s*\d{4}/\d{2}/[A-Z]/[A-Z]/\d{2}\s*$",
    re.IGNORECASE,
)
# Optional lined pages at the end of some papers ("Additional page") aren't part of any question.
END_OF_QUESTIONS_RE = re.compile(r"^\s*Additional page|If you use the following lined page", re.IGNORECASE)
# The copyright paragraph (and the rule above it) on the last page.
COPYRIGHT_BLOCK_RE = re.compile(r"Permission to reproduce items", re.IGNORECASE)
SESSIONS = {"M/J": "May/June", "O/N": "Oct/Nov", "F/M": "Feb/March"}
MAX_PAGES_BEFORE_FLAG = 2


# Symbol-font glyphs come through as Unicode private-use characters; map the common maths ones.
_SYMBOL_GLYPHS = {
    "": "+", "": "−", "": "=", "": "<", "": ">", "": "×",
    "": "÷", "": "≠", "": "≤", "": "≥", "": "±", "": "π",
    "": "°", "": "√", "": "(", "": ")", "": "[", "": "]",
    "": "{", "": "}", "": "(", "": ")", "": "{", "": "}",
    "": "[", "": "]", "": "θ", "": "α", "": "β",
}
_PRIVATE_USE_RE = re.compile("[-]")


def clean_text(text: str) -> str:
    text = "".join(_SYMBOL_GLYPHS.get(ch, ch) for ch in text)
    return " ".join(_PRIVATE_USE_RE.sub("", text).split())


class ExtractionError(ValueError):
    pass


@dataclass
class PaperInfo:
    syllabus_code: str
    component: str
    session: str  # e.g. "May/June"
    year: str  # e.g. "2023"

    @property
    def label(self) -> str:
        return f"{self.syllabus_code}/{self.component} {self.session} {self.year}"


@dataclass
class Segment:
    page: int
    rect: pymupdf.Rect
    mask: pymupdf.Rect | None = None  # the original question number, whited out when rendering


@dataclass
class ExtractedQuestion:
    number: int
    segments: list[Segment]
    text: str
    marks: int
    subparts: list[str]
    flags: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    info: PaperInfo | None
    questions: list[ExtractedQuestion]
    issues: list[str]


@dataclass
class _Anchor:
    number: int
    page: int
    y0: float
    bbox: pymupdf.Rect


@dataclass
class _Item:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str | None = None  # None for drawings

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or "bold" in span["font"].lower()


def _line_text(line: dict) -> str:
    return "".join(s["text"] for s in line["spans"])


def page_items(page: pymupdf.Page) -> list[_Item]:
    """Real content on a page: horizontal text lines and vector drawings, minus header/footer/boilerplate."""
    top, bottom = HEADER_ZONE, page.rect.height - FOOTER_ZONE
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        for line in block.get("lines", []):
            if COPYRIGHT_BLOCK_RE.search(_line_text(line)):
                bottom = min(bottom, line["bbox"][1] - 6)
    items: list[_Item] = []
    for block in blocks:
        for line in block.get("lines", []):
            text = _line_text(line)
            if not text.strip() or abs(line["dir"][1]) > 0.5 or BOILERPLATE_RE.search(text):
                continue
            x0, y0, x1, y1 = line["bbox"]
            if y1 <= top or y0 >= bottom:
                continue
            items.append(_Item(x0, y0, x1, y1, text))
    for drawing in page.get_drawings():
        r = drawing["rect"]
        if r.y1 <= top or r.y0 >= bottom or (r.width <= 0 and r.height <= 0):
            continue
        if r.width > page.rect.width * 0.9 and r.height > page.rect.height * 0.9:
            continue  # page frame/background, not content
        items.append(_Item(r.x0, r.y0, r.x1, r.y1))
    return items


def _paper_info(doc: pymupdf.Document) -> PaperInfo | None:
    for page in doc:
        m = PAPER_CODE_RE.search(page.get_text())
        if m:
            code, comp, s1, s2, yy = m.groups()
            return PaperInfo(code, comp, SESSIONS.get(f"{s1}/{s2}", f"{s1}/{s2}"), f"20{yy}")
    return None


def _number_bbox(page: pymupdf.Page, number: str, span_bbox) -> pymupdf.Rect:
    for w in page.get_text("words"):
        if w[4] == number and abs(w[0] - span_bbox[0]) < 1.5 and w[1] < span_bbox[3] and w[3] > span_bbox[1]:
            return pymupdf.Rect(w[:4])
    return pymupdf.Rect(span_bbox)


def _candidate_anchors(doc: pymupdf.Document) -> list[_Anchor]:
    out = []
    for pno, page in enumerate(doc):
        bottom = page.rect.height - FOOTER_ZONE
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans or abs(line["dir"][1]) > 0.5:
                    continue
                first = spans[0]
                m = QNUM_RE.match(first["text"])
                if not m or not _is_bold(first):
                    continue
                x0, y0 = first["bbox"][0], first["bbox"][1]
                if x0 > page.rect.width * 0.25 or y0 < HEADER_ZONE or y0 > bottom:
                    continue
                bbox = _number_bbox(page, m.group(1), first["bbox"])
                out.append(_Anchor(int(m.group(1)), pno, y0, bbox))
    return out


def _sequential_chain(candidates: list[_Anchor]) -> list[_Anchor]:
    chain, expected = [], 1
    for a in sorted(candidates, key=lambda a: (a.page, a.y0)):
        if a.number == expected:
            chain.append(a)
            expected += 1
    return chain


def find_question_anchors(doc: pymupdf.Document) -> tuple[list[_Anchor], list[str]]:
    candidates = _candidate_anchors(doc)
    clusters: list[list[_Anchor]] = []
    for a in sorted(candidates, key=lambda a: a.bbox.x0):
        if clusters and a.bbox.x0 - clusters[-1][-1].bbox.x0 <= 3:
            clusters[-1].append(a)
        else:
            clusters.append([a])
    logger.info("Found %d bold left-margin number(s) that could be question numbers", len(candidates))
    for a in candidates:
        logger.debug("  candidate %s on page %d at x=%.1f y=%.1f", a.number, a.page + 1, a.bbox.x0, a.y0)
    best: list[_Anchor] = []
    best_cluster: list[_Anchor] = []
    for cluster in clusters:
        chain = _sequential_chain(cluster)
        logger.debug(
            "  column at x≈%.1f: %d candidate(s), longest 1,2,3… run = %d", cluster[0].bbox.x0, len(cluster), len(chain)
        )
        if len(chain) > len(best):
            best, best_cluster = chain, cluster
    if best:
        logger.info(
            "Question-number column at x≈%.1f: questions %d–%d (%d ignored as stray numbers)",
            best[0].bbox.x0,
            best[0].number,
            best[-1].number,
            len(candidates) - len(best),
        )
    issues = []
    if best:
        last = best[-1].number
        later = sorted({a.number for a in best_cluster if a.number > last + 1})
        if later:
            issues.append(
                f"Question numbering stops at {last}, but numbers {', '.join(map(str, later))} also appear "
                "further on — some questions may be missing."
            )
    return best, issues


def _last_question_page(doc: pymupdf.Document, first_page: int) -> int:
    for pno in range(first_page + 1, len(doc)):
        if any(END_OF_QUESTIONS_RE.search(line) for line in doc[pno].get_text().splitlines()):
            return pno - 1
    return len(doc) - 1


def _content_columns(doc: pymupdf.Document, anchors: list[_Anchor], items_by_page: dict[int, list[_Item]]):
    x0 = min(a.bbox.x0 for a in anchors) - 6
    x1 = max((it.x1 for its in items_by_page.values() for it in its), default=doc[0].rect.width - 40) + 6
    width = doc[0].rect.width
    return max(0.0, x0), min(width - 10, x1)


def extract_questions(pdf_path: Path) -> ExtractionResult:
    doc = pymupdf.open(pdf_path)
    try:
        logger.info("Opened %s: %d page(s), PDF %s", pdf_path.name, len(doc), doc.metadata.get("format", "?"))
        text_pages = sum(1 for page in doc if page.get_text().strip())
        logger.info("Pages with a text layer: %d of %d", text_pages, len(doc))
        if not text_pages:
            raise ExtractionError(
                "This PDF has no text layer (probably a scan), so questions can't be located. "
                "Only born-digital PDFs are supported."
            )
        info = _paper_info(doc)
        anchors, issues = find_question_anchors(doc)
        if not anchors:
            raise ExtractionError(
                "No question numbers found. Is this a Cambridge question paper (not a mark scheme or insert)?"
            )
        if info is None:
            issues.append("Couldn't read the paper code (e.g. 0444/21/M/J/23) from the footer.")
            logger.warning("Paper code not found in any page footer")
        else:
            logger.info("Paper code: %s", info.label)

        last_page = _last_question_page(doc, anchors[-1].page)
        pages = range(anchors[0].page, last_page + 1)
        items_by_page = {p: page_items(doc[p]) for p in pages}
        col_x0, col_x1 = _content_columns(doc, anchors, items_by_page)
        skipped = [str(p + 1) for p in range(anchors[0].page)]
        logger.info(
            "Questions run from page %d to page %d%s; crop column x=%.1f–%.1f",
            anchors[0].page + 1,
            last_page + 1,
            f" (skipping cover/formula page(s) {', '.join(skipped)})" if skipped else "",
            col_x0,
            col_x1,
        )

        questions = []
        for i, anchor in enumerate(anchors):
            nxt = anchors[i + 1] if i + 1 < len(anchors) else None
            end_page = nxt.page if nxt else last_page
            segments: list[Segment] = []
            lines: list[str] = []
            for p in range(anchor.page, end_page + 1):
                page_h = doc[p].rect.height
                top = anchor.y0 if p == anchor.page else HEADER_ZONE
                ends_here = nxt is not None and p == nxt.page
                bottom = nxt.y0 if ends_here else page_h - FOOTER_ZONE
                # Tall maths (fractions, column vectors) can poke above its question number's line,
                # while the previous question always ends well clear of it (~24pt on CAIE papers).
                band = [
                    it
                    for it in items_by_page[p]
                    if it.y1 > top - OWNER_MARGIN and (not ends_here or it.y1 <= bottom - OWNER_MARGIN)
                ]
                if not band:
                    continue
                y0 = max(min(it.y0 for it in band) - PAD, HEADER_ZONE - 3)
                y1 = min(max(it.y1 for it in band) + PAD, bottom - 1, page_h - FOOTER_ZONE + 3)
                if y1 - y0 < 2:
                    continue
                mask = anchor.bbox if p == anchor.page else None
                segments.append(Segment(p, pymupdf.Rect(col_x0, y0, col_x1, y1), mask))
                logger.debug(
                    "  Q%d page %d: %d content item(s), crop y=%.1f–%.1f", anchor.number, p + 1, len(band), y0, y1
                )
                lines += [it.text for it in sorted(band, key=lambda it: (round(it.y0), it.x0)) if it.text]

            lines = [cleaned for line in lines if (cleaned := clean_text(line))]
            number_re = re.compile(rf"^{anchor.number}(?=\s|$)\s*")
            for idx, line in enumerate(lines):
                if number_re.match(line):
                    lines[idx] = number_re.sub("", line)
                    break
            text = "\n".join(line for line in lines if line)
            marks = sum(int(m) for m in MARKS_RE.findall(text))
            subparts = list(dict.fromkeys(m.group(1) for line in lines if (m := SUBPART_RE.match(line))))
            flags = []
            if not segments:
                flags.append("Nothing found to crop for this question.")
            if marks == 0:
                flags.append("No [n] mark allocation found in the question.")
            if len({s.page for s in segments}) > MAX_PAGES_BEFORE_FLAG:
                flags.append(f"Spans {len({s.page for s in segments})} pages — worth a quick look at the crop.")
            questions.append(ExtractedQuestion(anchor.number, segments, text, marks, subparts, flags))
            pages_used = sorted({sg.page + 1 for sg in segments})
            logger.info(
                "Q%d: %d mark(s), page(s) %s%s%s",
                anchor.number,
                marks,
                ", ".join(map(str, pages_used)) or "none",
                f", parts ({', '.join(subparts)})" if subparts else "",
                f" — FLAGGED: {'; '.join(flags)}" if flags else "",
            )
        logger.info(
            "Extracted %d question(s), %d marks in total, %d flagged",
            len(questions),
            sum(q.marks for q in questions),
            sum(1 for q in questions if q.flags),
        )
        for issue in issues:
            logger.warning("Paper check: %s", issue)
        return ExtractionResult(info, questions, issues)
    finally:
        doc.close()


def render_segments(pdf_path: Path, segments: list[Segment], out_path: Path, scale: float = RENDER_SCALE) -> None:
    """Stitch one or more page regions into a single PNG, top to bottom, keeping vector quality until the final render."""
    if not segments:
        raise ValueError("No segments to render")
    src = pymupdf.open(pdf_path)
    out = pymupdf.open()
    try:
        width = max(s.rect.width for s in segments)
        height = sum(s.rect.height for s in segments) + SEGMENT_GAP * (len(segments) - 1)
        page = out.new_page(width=width, height=height)
        y = 0.0
        for s in segments:
            target = pymupdf.Rect(0, y, s.rect.width, y + s.rect.height)
            page.show_pdf_page(target, src, s.page, clip=s.rect)
            if s.mask is not None:
                m = s.mask + (-1, -1, 1, 1)
                page.draw_rect(
                    pymupdf.Rect(m.x0 - s.rect.x0, y + m.y0 - s.rect.y0, m.x1 - s.rect.x0, y + m.y1 - s.rect.y0),
                    color=None,
                    fill=(1, 1, 1),
                )
            y += s.rect.height + SEGMENT_GAP
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        pix.save(str(out_path))
        logger.debug(
            "  rendered %s: %d segment(s), %dx%d px, %.0f KB",
            out_path.name,
            len(segments),
            pix.width,
            pix.height,
            out_path.stat().st_size / 1024,
        )
    finally:
        out.close()
        src.close()
