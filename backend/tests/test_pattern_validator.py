import json
from pathlib import Path

import pytest

from app.config import REPO_ROOT
from app.services.pattern_validator import (
    PatternValidationError,
    total_marks,
    total_question_count,
    validate_pattern_config,
)

SAMPLE_PATTERN_PATH = REPO_ROOT / "config" / "patterns" / "example_cbse_class10_science_term1.json"


def _load_sample() -> dict:
    return json.loads(Path(SAMPLE_PATTERN_PATH).read_text())


def test_sample_pattern_is_valid():
    validate_pattern_config(_load_sample())  # should not raise


def test_missing_required_field_rejected():
    config = _load_sample()
    del config["sections"]
    with pytest.raises(PatternValidationError):
        validate_pattern_config(config)


def test_bad_question_type_rejected():
    config = _load_sample()
    config["sections"][0]["question_type"] = "ESSAY"  # not in the allowed enum
    with pytest.raises(PatternValidationError):
        validate_pattern_config(config)


def test_total_marks_and_question_count():
    config = _load_sample()
    assert total_marks(config) == 49
    assert total_question_count(config) == 23
