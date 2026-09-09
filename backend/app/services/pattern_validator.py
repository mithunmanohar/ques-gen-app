"""
Validates a Pattern's config_json against config/pattern.schema.json.

Patterns are the "spec" that drives generation: they describe an exam
blueprint (sections, question types, marks, counts) independently of any
particular subject content. Keeping this schema-validated means the admin
UI can give a non-technical user a clear error message instead of a stack
trace, and means a hand-edited JSON file dropped into config/patterns/
is caught early too.
"""
import json
from pathlib import Path

from jsonschema import Draft7Validator

from ..config import REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "config" / "pattern.schema.json"


class PatternValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate_pattern_config(config: dict) -> None:
    """Raises PatternValidationError with all problems found, if any."""
    schema = load_schema()
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(config), key=lambda e: list(e.path))
    if errors:
        messages = [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in errors]
        raise PatternValidationError(messages)


def total_marks(config: dict) -> float:
    return sum(
        section.get("num_questions", 0) * section.get("marks_per_question", 0)
        for section in config.get("sections", [])
    )


def total_question_count(config: dict) -> int:
    return sum(section.get("num_questions", 0) for section in config.get("sections", []))
