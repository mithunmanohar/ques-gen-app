from datetime import datetime

from pydantic import BaseModel, ConfigDict


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


class QuestionWithAnswerOut(QuestionOut):
    expected_answer: str
    rubric: str


class QuestionSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    pattern_id: int
    subject: str
    grade: str
    status: str
    error_message: str = ""
    generated_at: datetime
    questions: list[QuestionOut] = []


class QuestionSetAnswerKeyOut(QuestionSetOut):
    questions: list[QuestionWithAnswerOut] = []  # type: ignore[assignment]


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
    submitted_at: datetime
    images: list[SubmissionImageOut] = []
    evaluation: EvaluationOut | None = None
