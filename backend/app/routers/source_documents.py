import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models, schemas
from ..config import get_settings
from ..db import get_db
from ..services import ingestion

router = APIRouter(prefix="/api/source-documents", tags=["source-documents"])


@router.get("", response_model=list[schemas.SourceDocumentOut])
def list_source_documents(db: Session = Depends(get_db)):
    docs = db.query(models.SourceDocument).order_by(models.SourceDocument.uploaded_at.desc()).all()
    return [_to_out(d) for d in docs]


def _to_out(doc: models.SourceDocument) -> schemas.SourceDocumentOut:
    out = schemas.SourceDocumentOut.model_validate(doc)
    out.text_preview = (doc.extracted_text or "")[:400]
    return out


@router.post("", response_model=schemas.SourceDocumentOut)
async def upload_source_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    subject: str = Form(""),
    grade: str = Form(""),
    chapter: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        file_type = ingestion.file_type_for(file.filename)
    except ingestion.UnsupportedFileType as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    settings = get_settings()
    dest_filename = f"{uuid.uuid4().hex}_{file.filename}"
    dest_path = await ingestion.save_upload(file, settings.source_documents_dir, dest_filename)

    try:
        extracted_text = ingestion.extract_text(dest_path, file_type)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not read file: {e}") from e

    doc = models.SourceDocument(
        title=title or file.filename,
        subject=subject,
        grade=grade,
        chapter=chapter,
        original_filename=file.filename,
        file_type=file_type,
        file_path=str(dest_path),
        extracted_text=extracted_text,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _to_out(doc)


@router.delete("/{document_id}", status_code=204)
def delete_source_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(models.SourceDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Source document not found")
    try:
        Path(doc.file_path).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(doc)
    db.commit()
