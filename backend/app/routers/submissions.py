import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import get_settings
from ..db import get_db
from ..services import ingestion
from ..services.evaluation import evaluate_submission

router = APIRouter(prefix="/api/submissions", tags=["submissions"])
logger = logging.getLogger(__name__)


@router.get("", response_model=list[schemas.SubmissionOut])
def list_submissions(question_set_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Submission)
    if question_set_id is not None:
        query = query.filter(models.Submission.question_set_id == question_set_id)
    return query.order_by(models.Submission.submitted_at.desc()).all()


@router.post("", response_model=schemas.SubmissionOut)
async def create_submission(
    question_set_id: int = Form(...),
    student_name: str = Form(""),
    images: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    question_set = db.get(models.QuestionSet, question_set_id)
    if not question_set:
        raise HTTPException(status_code=404, detail="Question set not found")
    if not images:
        raise HTTPException(status_code=400, detail="At least one answer-sheet image is required")

    submission = models.Submission(question_set_id=question_set_id, student_name=student_name)
    db.add(submission)
    db.commit()
    db.refresh(submission)

    settings = get_settings()
    submission_dir = settings.submissions_dir / str(submission.id)
    for idx, image in enumerate(images):
        dest_filename = f"{uuid.uuid4().hex}_{image.filename}"
        dest_path = await ingestion.save_upload(image, submission_dir, dest_filename)
        db.add(
            models.SubmissionImage(
                submission_id=submission.id,
                order_index=idx,
                file_path=str(dest_path),
                original_filename=image.filename,
            )
        )
        logger.info("Saved answer-sheet photo %d: %s (%.0f KB)", idx + 1, image.filename, dest_path.stat().st_size / 1024)
    logger.info(
        "Submission #%d created for question set #%d ('%s') with %d photo(s)",
        submission.id,
        question_set.id,
        question_set.name,
        len(images),
    )
    db.commit()
    db.refresh(submission)
    return submission


@router.post("/{submission_id}/evaluate", response_model=schemas.SubmissionOut)
def evaluate(submission_id: int, db: Session = Depends(get_db)):
    submission = db.get(models.Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    try:
        evaluate_submission(db, submission)
    except Exception as e:  # noqa: BLE001 — error is already recorded on the submission; report it too
        raise HTTPException(
            status_code=502,
            detail=f"Grading failed ({type(e).__name__}): {e}. The submission's grading log has the details.",
        ) from e
    db.refresh(submission)
    return submission


@router.get("/{submission_id}", response_model=schemas.SubmissionOut)
def get_submission(submission_id: int, db: Session = Depends(get_db)):
    submission = db.get(models.Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submission
