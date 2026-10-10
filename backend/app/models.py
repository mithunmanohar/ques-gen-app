"""
SQLAlchemy ORM models.

Data flow this schema supports:

  SourceDocument (uploaded past-year paper, PDF/MD/TXT, text extracted)
        |
        v  (used as raw material for a prompt, alongside a Pattern)
  Pattern (JSON exam blueprint: sections, question types, marks, counts)
        |
        v
  QuestionSet -> Question (AI-generated, includes hidden expected_answer/rubric)
        |
        v
  Submission (a child's attempt at one QuestionSet) -> SubmissionImage(s)
        |
        v
  Evaluation -> EvaluationItem (per-question grading result)

Past-paper bank (a second way to build a QuestionSet):

  PastPaper (an uploaded Cambridge question paper + optional mark scheme)
        |
        v  (automatic extraction: one cropped image per question)
  BankQuestion (image, text, marks, topics, official mark-scheme entries)
        |
        v  (picked at random to hit a marks target)
  QuestionSet -> Question (with bank_question_id set)
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(100), default="")
    grade: Mapped[str] = mapped_column(String(50), default="")
    chapter: Mapped[str] = mapped_column(String(255), default="")
    original_filename: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str] = mapped_column(String(20))  # pdf | md | txt
    file_path: Mapped[str] = mapped_column(String(500))
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Pattern(Base):
    __tablename__ = "patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(100), default="")
    grade: Mapped[str] = mapped_column(String(50), default="")
    config_json: Mapped[dict] = mapped_column(JSON)  # validated against config/pattern.schema.json
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    question_sets: Mapped[list["QuestionSet"]] = relationship(back_populates="pattern")


class PastPaper(Base):
    __tablename__ = "past_papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(String(100), default="")
    syllabus_code: Mapped[str] = mapped_column(String(20), default="")
    component: Mapped[str] = mapped_column(String(20), default="")
    session: Mapped[str] = mapped_column(String(30), default="")
    year: Mapped[str] = mapped_column(String(10), default="")
    qp_filename: Mapped[str] = mapped_column(String(255))
    ms_filename: Mapped[str] = mapped_column(String(255), default="")
    storage_dir: Mapped[str] = mapped_column(String(500), default="")
    max_mark: Mapped[int | None] = mapped_column(Integer, nullable=True)  # from the mark scheme
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing | ready | failed
    issues: Mapped[list] = mapped_column(JSON, default=list)  # paper-level automatic-check warnings
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    questions: Mapped[list["BankQuestion"]] = relationship(
        back_populates="past_paper", order_by="BankQuestion.number", cascade="all, delete-orphan"
    )

    @property
    def paper_code(self) -> str:
        if not self.syllabus_code:
            return ""
        return f"{self.syllabus_code}/{self.component} {self.session} {self.year}".strip()

    @property
    def total_marks(self) -> int:
        return int(sum(q.marks for q in self.questions))

    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def flagged_count(self) -> int:
        return sum(1 for q in self.questions if q.flags)

    @property
    def needs_attention(self) -> bool:
        return bool(self.issues) or self.flagged_count > 0


class BankQuestion(Base):
    __tablename__ = "bank_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    past_paper_id: Mapped[int] = mapped_column(ForeignKey("past_papers.id"))
    number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")  # text layer — maths layout is lossy; the image is canonical
    marks: Mapped[float] = mapped_column(Float, default=0)
    subparts: Mapped[list] = mapped_column(JSON, default=list)
    topics: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)  # question-level automatic-check warnings
    image_path: Mapped[str] = mapped_column(String(500), default="")
    ms_entries: Mapped[list] = mapped_column(JSON, default=list)  # [{label, answer, marks, partial_marks}]
    ms_image_path: Mapped[str] = mapped_column(String(500), default="")

    past_paper: Mapped["PastPaper"] = relationship(back_populates="questions")

    @property
    def image_url(self) -> str:
        return f"/api/bank-questions/{self.id}/image"

    @property
    def ms_image_url(self) -> str | None:
        return f"/api/bank-questions/{self.id}/mark-scheme-image" if self.ms_image_path else None

    @property
    def source_label(self) -> str:
        code = self.past_paper.paper_code if self.past_paper else ""
        return f"{code} Q{self.number}".strip()


class QuestionSet(Base):
    __tablename__ = "question_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    pattern_id: Mapped[int | None] = mapped_column(ForeignKey("patterns.id"), nullable=True)  # None for bank sets
    source: Mapped[str] = mapped_column(String(20), default="ai")  # ai | bank
    subject: Mapped[str] = mapped_column(String(100), default="")
    grade: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(20), default="ready")  # generating | ready | failed
    error_message: Mapped[str] = mapped_column(Text, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    pattern: Mapped["Pattern"] = relationship(back_populates="question_sets")
    questions: Mapped[list["Question"]] = relationship(
        back_populates="question_set", order_by="Question.order_index", cascade="all, delete-orphan"
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_set_id: Mapped[int] = mapped_column(ForeignKey("question_sets.id"))
    section: Mapped[str] = mapped_column(String(20), default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    question_type: Mapped[str] = mapped_column(String(30), default="SA")  # MCQ|VSA|SA|LA|CASE_STUDY
    text: Mapped[str] = mapped_column(Text)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)  # for MCQ
    marks: Mapped[float] = mapped_column(Float, default=1)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium")

    # Not shown to the student in the printable view — used only for grading.
    expected_answer: Mapped[str] = mapped_column(Text, default="")
    rubric: Mapped[str] = mapped_column(Text, default="")

    # Set when the question was picked from the past-paper bank rather than AI-generated.
    bank_question_id: Mapped[int | None] = mapped_column(ForeignKey("bank_questions.id"), nullable=True)

    question_set: Mapped["QuestionSet"] = relationship(back_populates="questions")
    bank_question: Mapped["BankQuestion | None"] = relationship()

    @property
    def image_url(self) -> str | None:
        return self.bank_question.image_url if self.bank_question else None

    @property
    def answer_key_image_url(self) -> str | None:
        return self.bank_question.ms_image_url if self.bank_question else None

    @property
    def source_label(self) -> str:
        return self.bank_question.source_label if self.bank_question else ""


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_set_id: Mapped[int] = mapped_column(ForeignKey("question_sets.id"))
    student_name: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="submitted")  # submitted|evaluating|evaluated|failed
    error_message: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    images: Mapped[list["SubmissionImage"]] = relationship(
        back_populates="submission", order_by="SubmissionImage.order_index", cascade="all, delete-orphan"
    )
    evaluation: Mapped["Evaluation"] = relationship(
        back_populates="submission", uselist=False, cascade="all, delete-orphan"
    )


class SubmissionImage(Base):
    __tablename__ = "submission_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    file_path: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))

    submission: Mapped["Submission"] = relationship(back_populates="images")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), unique=True)
    total_marks_awarded: Mapped[float] = mapped_column(Float, default=0)
    total_marks_possible: Mapped[float] = mapped_column(Float, default=0)
    overall_feedback: Mapped[str] = mapped_column(Text, default="")
    is_mocked: Mapped[bool] = mapped_column(Boolean, default=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    submission: Mapped["Submission"] = relationship(back_populates="evaluation")
    items: Mapped[list["EvaluationItem"]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan"
    )


class EvaluationItem(Base):
    __tablename__ = "evaluation_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id"))
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    extracted_answer: Mapped[str] = mapped_column(Text, default="")
    marks_awarded: Mapped[float] = mapped_column(Float, default=0)
    marks_possible: Mapped[float] = mapped_column(Float, default=0)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[str] = mapped_column(Text, default="")

    evaluation: Mapped["Evaluation"] = relationship(back_populates="items")
    question: Mapped["Question"] = relationship()
