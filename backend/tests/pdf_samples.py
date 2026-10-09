"""
Builds small synthetic Cambridge-style PDFs for tests, laid out like the real
thing (bold question numbers at x≈49.6pt, footer code, ruled mark-scheme table)
so no copyrighted papers need to live in the repo.

Question paper (4 questions, 10 marks):
  p1  cover page with non-bold margin digits (like a candidate barcode)
  p2  Q1 (text + triangle diagram, [2]), Q2 (a)[1] (b)[2], Q3 part (a)[2] …
  p3  … Q3 continues: (b)[1], then Q4 [2]
  p4  BLANK PAGE
"""
from pathlib import Path

import pymupdf

W, H = 595.28, 841.89
QX = 49.6  # question-number column
TX = 78.0  # question text column


def _footer(page: pymupdf.Page, number: int | None, code: str = "0444/21/M/J/23") -> None:
    if number is not None:
        page.insert_text((W / 2 - 3, 46), str(number), fontname="tiro", fontsize=11)
    page.insert_text((QX, 805), "© UCLES 2023", fontname="tiro", fontsize=9)
    page.insert_text((W / 2 - 30, 805), code, fontname="tiro", fontsize=9)


def _question_number(page: pymupdf.Page, y: float, number: int) -> None:
    page.insert_text((QX, y), str(number), fontname="tibo", fontsize=11)


def _text(page: pymupdf.Page, x: float, y: float, text: str) -> None:
    page.insert_text((x, y), text, fontname="tiro", fontsize=11)


def _answer_line(page: pymupdf.Page, y: float, marks: int) -> None:
    _text(page, 380, y, "." * 40 + f" [{marks}]")


def make_question_paper(path: Path, code: str = "0444/21/M/J/23") -> Path:
    doc = pymupdf.open()

    cover = doc.new_page(width=W, height=H)
    _text(cover, 200, 120, "Cambridge IGCSE")
    _text(cover, 200, 140, "MATHEMATICS")
    for i, digit in enumerate("0444210"):
        cover.insert_text((17.7, 300 + 14 * i), digit, fontname="tiro", fontsize=9)
    _footer(cover, None, code)

    p2 = doc.new_page(width=W, height=H)
    _question_number(p2, 72, 1)
    p2.draw_polyline([(150, 200), (300, 90), (380, 200), (150, 200)], color=(0, 0, 0), width=1)
    _text(p2, 160, 215, "A")
    _text(p2, TX, 240, "Find angle ABC.")
    _answer_line(p2, 300, 2)

    _question_number(p2, 360, 2)
    _text(p2, TX, 360, "(a) Work out 3 + 4.")
    _answer_line(p2, 420, 1)
    _text(p2, TX, 460, "(b) Work out 5 x 6.")
    _answer_line(p2, 520, 2)

    _question_number(p2, 600, 3)
    _text(p2, TX, 600, "(a) Solve x + 2 = 5.")
    _answer_line(p2, 680, 2)
    _text(p2, 220, 772, "Questions 3 and 4 are printed on the next page.")
    _footer(p2, 2, code)

    p3 = doc.new_page(width=W, height=H)
    _text(p3, TX, 80, "(b) Write down the value of x + 1.")
    _answer_line(p3, 140, 1)
    _question_number(p3, 260, 4)
    _text(p3, TX, 260, "Expand 2(x + 3).")
    _answer_line(p3, 330, 2)
    _footer(p3, 3, code)

    p4 = doc.new_page(width=W, height=H)
    _text(p4, W / 2 - 40, H / 2, "BLANK PAGE")
    _footer(p4, 4, code)

    doc.save(path)
    doc.close()
    return path


MS_RULES = [49.0, 113.0, 326.0, 375.0, 546.0]
MS_ROWS = [
    ("1", "51", "2", "M1 for 180 - 129"),
    ("2(a)", "7", "1", ""),
    ("2(b)", "30", "2", "M1 for 5 x 6"),
    ("3(a)", "3", "2", "M1 for x = 5 - 2"),
    ("3(b)", "4", "1", "FT their (a) + 1"),
    ("4", "2x + 6", "2", "B1 for 2x or 6"),
]


def make_mark_scheme(path: Path, max_mark: int = 10, code: str = "0444/21", session: str = "May/June 2023") -> Path:
    doc = pymupdf.open()
    p1 = doc.new_page(width=W, height=H)
    _text(p1, 200, 120, "Cambridge IGCSE")
    _text(p1, 200, 140, code)
    _text(p1, 200, 160, session)
    _text(p1, 200, 180, "MARK SCHEME")
    _text(p1, 200, 200, f"Maximum Mark: {max_mark}")

    p2 = doc.new_page(width=W, height=H)
    _text(p2, QX, 46, code)
    row_h = 30
    top = 62.0
    seps = [top + row_h * i for i in range(len(MS_ROWS) + 2)]
    for y in seps:
        p2.draw_line((MS_RULES[0], y), (MS_RULES[-1], y), color=(0, 0, 0), width=0.5)
    for x in MS_RULES:
        p2.draw_line((x, seps[0]), (x, seps[-1]), color=(0, 0, 0), width=0.5)
    header_y = seps[0] + 19
    for x, word in ((60, "Question"), (200, "Answer"), (335, "Marks"), (420, "Partial Marks")):
        p2.insert_text((x, header_y), word, fontname="tibo", fontsize=11)
    for i, (label, answer, marks, partial) in enumerate(MS_ROWS):
        y = seps[i + 1] + 19
        _text(p2, 72, y, label)
        _text(p2, 120, y, answer)
        _text(p2, 360, y, marks)
        if partial:
            _text(p2, 380, y, partial)
    _footer(p2, None, code)
    doc.save(path)
    doc.close()
    return path
