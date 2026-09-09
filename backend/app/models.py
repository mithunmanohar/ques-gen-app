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


class QuestionSet(Base):
    __tablename__ = "question_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    pattern_id: Mapped[int] = mapped_column(ForeignKey("patterns.id"))
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

    question_set: Mapped["QuestionSet"] = relationship(back_populates="questions")


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
