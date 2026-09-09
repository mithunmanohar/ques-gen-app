from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services.generation import generate_question_set

router = APIRouter(prefix="/api/question-sets", tags=["question-sets"])


@router.get("", response_model=list[schemas.QuestionSetOut])
def list_question_sets(db: Session = Depends(get_db)):
    return db.query(models.QuestionSet).order_by(models.QuestionSet.generated_at.desc()).all()


@router.post("/generate", response_model=list[schemas.QuestionSetOut])
def generate(payload: schemas.GenerateRequest, db: Session = Depends(get_db)):
    pattern = db.get(models.Pattern, payload.pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")

    source_documents = []
    if payload.source_document_ids:
        source_documents = (
            db.query(models.SourceDocument)
            .filter(models.SourceDocument.id.in_(payload.source_document_ids))
            .all()
        )

    num_sets = max(1, min(payload.num_sets, 10))  # sane upper bound per request
    results = []
    for i in range(num_sets):
        set_name = payload.name or f"{pattern.name}"
        if num_sets > 1:
            set_name = f"{set_name} — Set {i + 1}"
        question_set = generate_question_set(
            db,
            pattern=pattern,
            name=set_name,
            source_documents=source_documents,
            extra_instructions=payload.extra_instructions,
        )
        results.append(question_set)
    return results


@router.get("/{question_set_id}", response_model=schemas.QuestionSetOut)
def get_question_set(question_set_id: int, db: Session = Depends(get_db)):
    """Student-facing view: question text only, no expected_answer/rubric."""
    question_set = db.get(models.QuestionSet, question_set_id)
    if not question_set:
        raise HTTPException(status_code=404, detail="Question set not found")
    return question_set


@router.get("/{question_set_id}/answer-key", response_model=schemas.QuestionSetAnswerKeyOut)
def get_question_set_answer_key(question_set_id: int, db: Session = Depends(get_db)):
    """Teacher-facing view: includes the hidden expected_answer/rubric for each question."""
    question_set = db.get(models.QuestionSet, question_set_id)
    if not question_set:
        raise HTTPException(status_code=404, detail="Question set not found")
    return question_set


@router.delete("/{question_set_id}", status_code=204)
def delete_question_set(question_set_id: int, db: Session = Depends(get_db)):
    question_set = db.get(models.QuestionSet, question_set_id)
    if not question_set:
        raise HTTPException(status_code=404, detail="Question set not found")
    db.delete(question_set)
    db.commit()
