import shutil
from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import get_settings
from ..db import get_db
from ..services import ingestion
from ..services.past_paper_import import import_past_paper

router = APIRouter(prefix="/api", tags=["past-papers"])


def _require_pdf(upload: UploadFile, what: str) -> None:
    if Path(upload.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail=f"The {what} must be a PDF.")


@router.get("/past-papers", response_model=list[schemas.PastPaperOut])
def list_past_papers(db: Session = Depends(get_db)):
    return db.query(models.PastPaper).order_by(models.PastPaper.uploaded_at.desc()).all()


@router.post("/past-papers", response_model=schemas.PastPaperDetailOut)
async def upload_past_paper(
    question_paper: UploadFile = File(...),
    mark_scheme: UploadFile | None = File(None),
    title: str = Form(""),
    subject: str = Form(""),
    db: Session = Depends(get_db),
):
    _require_pdf(question_paper, "question paper")
    has_ms = mark_scheme is not None and bool(mark_scheme.filename)
    if has_ms:
        _require_pdf(mark_scheme, "mark scheme")

    paper = models.PastPaper(
        title=title.strip(),
        subject=subject.strip(),
        qp_filename=question_paper.filename,
        ms_filename=mark_scheme.filename if has_ms else "",
        status="processing",
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)

    storage_dir = get_settings().past_papers_dir / str(paper.id)
    paper.storage_dir = str(storage_dir)
    qp_path = await ingestion.save_upload(question_paper, storage_dir, "question_paper.pdf")
    ms_path = await ingestion.save_upload(mark_scheme, storage_dir, "mark_scheme.pdf") if has_ms else None
    db.commit()

    paper = import_past_paper(db, paper, qp_path, ms_path)
    if not paper.title:
        paper.title = Path(question_paper.filename).stem
        db.commit()
        db.refresh(paper)
    return paper


@router.get("/past-papers/{paper_id}", response_model=schemas.PastPaperDetailOut)
def get_past_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.get(models.PastPaper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Past paper not found")
    return paper


@router.delete("/past-papers/{paper_id}", status_code=204)
def delete_past_paper(paper_id: int, db: Session = Depends(get_db)):
    paper = db.get(models.PastPaper, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Past paper not found")
    used_in = (
        db.query(models.QuestionSet.name)
        .join(models.Question)
        .join(models.BankQuestion, models.Question.bank_question_id == models.BankQuestion.id)
        .filter(models.BankQuestion.past_paper_id == paper_id)
        .distinct()
        .all()
    )
    if used_in:
        names = ", ".join(f"'{n}'" for (n,) in used_in[:5])
        raise HTTPException(
            status_code=409,
            detail=f"Questions from this paper are used in question set(s) {names}. Delete those sets first.",
        )
    storage_dir = paper.storage_dir
    db.delete(paper)
    db.commit()
    if storage_dir:
        shutil.rmtree(storage_dir, ignore_errors=True)


@router.get("/bank-questions", response_model=list[schemas.BankQuestionOut])
def list_bank_questions(past_paper_id: int | None = None, topic: str = "", db: Session = Depends(get_db)):
    query = db.query(models.BankQuestion)
    if past_paper_id is not None:
        query = query.filter(models.BankQuestion.past_paper_id == past_paper_id)
    questions = query.order_by(models.BankQuestion.past_paper_id, models.BankQuestion.number).all()
    if topic.strip():
        wanted = topic.strip().lower()
        questions = [q for q in questions if wanted in (t.lower() for t in q.topics)]
    return questions


@router.get("/bank-questions/topics", response_model=list[schemas.TopicCount])
def list_bank_topics(db: Session = Depends(get_db)):
    counts = Counter(t for (topics,) in db.query(models.BankQuestion.topics).all() for t in topics or [])
    return [schemas.TopicCount(topic=t, count=n) for t, n in sorted(counts.items(), key=lambda kv: kv[0].lower())]


def _image_response(path: str) -> FileResponse:
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/png")


@router.get("/bank-questions/{question_id}/image")
def bank_question_image(question_id: int, db: Session = Depends(get_db)):
    question = db.get(models.BankQuestion, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Bank question not found")
    return _image_response(question.image_path)


@router.get("/bank-questions/{question_id}/mark-scheme-image")
def bank_question_mark_scheme_image(question_id: int, db: Session = Depends(get_db)):
    question = db.get(models.BankQuestion, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="Bank question not found")
    return _image_response(question.ms_image_path)
