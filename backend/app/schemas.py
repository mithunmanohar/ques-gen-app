from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


# Rows created before processing logs existed hold NULL; show them as an empty log.
LogLines = Annotated[list[str], BeforeValidator(lambda v: v or [])]


class SourceDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    subject: str
    grade: str
    chapter: str
    original_filename: str
    file_type: str
    uploaded_at: datetime
    text_preview: str = ""


class PatternIn(BaseModel):
    name: str
    subject: str = ""
    grade: str = ""
    config_json: dict


class PatternOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: str
    grade: str
    config_json: dict
    created_at: datetime
    updated_at: datetime


class GenerateRequest(BaseModel):
    pattern_id: int
    name: str = ""
    num_sets: int = 1
    source_document_ids: list[int] = []
    extra_instructions: str = ""


class BankSetRequest(BaseModel):
    name: str = ""
    num_sets: int = Field(1, ge=1, le=10)
    target_marks: float = Field(40, gt=0, le=500)
    past_paper_ids: list[int] = []  # empty = every ready paper
    topics: list[str] = []  # empty = any topic
    avoid_used: bool = True  # skip questions already used in any earlier set
    include_flagged: bool = False  # include questions the automatic checks flagged


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    section: str
    order_index: int
    question_type: str
    text: str
    options: list | None = None
    marks: float
    difficulty: str
    image_url: str | None = None  # past-paper questions: the cropped question image is canonical


class QuestionWithAnswerOut(QuestionOut):
    expected_answer: str
    rubric: str
    answer_key_image_url: str | None = None
    source_label: str = ""


class QuestionSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pattern_id: int | None = None
    source: str = "ai"
    subject: str
    grade: str
    status: str
    error_message: str = ""
    processing_log: LogLines = []
    generated_at: datetime
    questions: list[QuestionOut] = []


class QuestionSetAnswerKeyOut(QuestionSetOut):
    questions: list[QuestionWithAnswerOut] = []  # type: ignore[assignment]


class BankQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    past_paper_id: int
    number: int
    marks: float
    subparts: list[str] = []
    topics: list[str] = []
    flags: list[str] = []
    text: str
    image_url: str
    ms_entries: list[dict] = []
    ms_image_url: str | None = None
    source_label: str = ""


class PastPaperOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    subject: str
    paper_code: str
    qp_filename: str
    ms_filename: str
    max_mark: int | None = None
    total_marks: int
    question_count: int
    flagged_count: int
    needs_attention: bool
    status: str
    issues: list[str] = []
    processing_log: LogLines = []
    uploaded_at: datetime


class PastPaperDetailOut(PastPaperOut):
    questions: list[BankQuestionOut] = []


class TopicCount(BaseModel):
    topic: str
    count: int


class SubmissionImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_index: int
    original_filename: str


class EvaluationItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    question_id: int
    extracted_answer: str
    marks_awarded: float
    marks_possible: float
    is_correct: bool
    feedback: str


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_marks_awarded: float
    total_marks_possible: float
    overall_feedback: str
    is_mocked: bool
    evaluated_at: datetime
    items: list[EvaluationItemOut] = []


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question_set_id: int
    student_name: str
    status: str
    error_message: str = ""
    processing_log: LogLines = []
    submitted_at: datetime
    images: list[SubmissionImageOut] = []
    evaluation: EvaluationOut | None = None
