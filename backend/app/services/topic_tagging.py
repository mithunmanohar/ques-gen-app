"""
Tags each extracted past-paper question with 1-3 syllabus topics using DeepSeek,
so new sets can be built by topic ("only Trigonometry and Algebra").

Runs once per paper at import time. Tagging is best-effort: if it fails (or
mock mode is on) questions are simply left untagged and the import still
succeeds — topics only narrow selection, they're never required.
"""
import logging

from . import deepseek_client

logger = logging.getLogger(__name__)

MAX_CHARS_PER_QUESTION = 1200

# Suggested vocabulary so tags stay consistent across papers. The model may use
# another short name when nothing here fits (e.g. for non-maths subjects).
SUGGESTED_TOPICS = [
    "Number", "Algebra", "Equations & inequalities", "Sequences", "Functions", "Graphs",
    "Coordinate geometry", "Geometry", "Mensuration", "Trigonometry", "Vectors",
    "Transformations", "Probability", "Statistics", "Sets", "Ratio & proportion",
    "Percentages & finance", "Indices & surds", "Variation", "Calculus",
]

SYSTEM_PROMPT = """You classify exam questions by syllabus topic.

You get the questions of one past exam paper. Their text was extracted from a PDF, so \
mathematical notation may be garbled (fractions and powers broken onto separate lines) — \
infer the topic from what is recognisable.

For each question give 1 to 3 short topic names, most important first. Use names from the \
suggested list whenever one fits, spelled exactly as listed, so the same topic always has \
the same name.

Respond with a single JSON object and nothing else:
{"questions": [{"number": <question number>, "topics": ["<topic>", ...]}]}"""


def _build_user_prompt(subject: str, paper_code: str, questions: list[tuple[int, str]]) -> str:
    lines = [
        f"Subject: {subject or 'unknown'}",
        f"Paper: {paper_code or 'unknown'}",
        "Suggested topics: " + ", ".join(SUGGESTED_TOPICS),
        "",
        "Questions:",
    ]
    for number, text in questions:
        lines.append(f"--- Question {number} ---")
        lines.append(text[:MAX_CHARS_PER_QUESTION])
    return "\n".join(lines)


def tag_topics(subject: str, paper_code: str, questions: list[tuple[int, str]]) -> dict[int, list[str]]:
    """Returns {question number: [topics]}. Raises deepseek_client.DeepSeekError on API failure."""
    if not questions:
        return {}
    logger.info("Asking DeepSeek to tag topics for %d question(s)", len(questions))
    response = deepseek_client.chat_json(
        SYSTEM_PROMPT,
        _build_user_prompt(subject, paper_code, questions),
        mock_response={"questions": []},  # mock mode: leave untagged rather than invent topics
    )
    out: dict[int, list[str]] = {}
    for entry in response.get("questions", []):
        try:
            number = int(entry.get("number"))
        except (TypeError, ValueError):
            logger.warning("Ignoring topic entry without a valid question number: %r", entry)
            continue
        topics = [str(t).strip() for t in entry.get("topics", []) if str(t).strip()]
        out[number] = list(dict.fromkeys(topics))[:3]
        logger.debug("  Q%d topics: %s", number, out[number])
    missing = sorted({n for n, _ in questions} - set(out))
    if missing and out:
        logger.warning("No topics returned for question(s) %s", ", ".join(map(str, missing)))
    return out
