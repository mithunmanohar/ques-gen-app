from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..db import get_db
from ..services.pattern_validator import PatternValidationError, load_schema, validate_pattern_config

router = APIRouter(prefix="/api/patterns", tags=["patterns"])


@router.get("", response_model=list[schemas.PatternOut])
def list_patterns(db: Session = Depends(get_db)):
    return db.query(models.Pattern).order_by(models.Pattern.updated_at.desc()).all()


@router.get("/schema")
def get_pattern_schema():
    """Serves config/pattern.schema.json so the admin UI can render/validate a form from it."""
    return load_schema()


@router.post("", response_model=schemas.PatternOut)
def create_pattern(payload: schemas.PatternIn, db: Session = Depends(get_db)):
    try:
        validate_pattern_config(payload.config_json)
    except PatternValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e

    pattern = models.Pattern(
        name=payload.name,
        subject=payload.subject,
        grade=payload.grade,
        config_json=payload.config_json,
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return pattern


@router.get("/{pattern_id}", response_model=schemas.PatternOut)
def get_pattern(pattern_id: int, db: Session = Depends(get_db)):
    pattern = db.get(models.Pattern, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return pattern


@router.put("/{pattern_id}", response_model=schemas.PatternOut)
def update_pattern(pattern_id: int, payload: schemas.PatternIn, db: Session = Depends(get_db)):
    pattern = db.get(models.Pattern, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    try:
        validate_pattern_config(payload.config_json)
    except PatternValidationError as e:
        raise HTTPException(status_code=422, detail={"errors": e.errors}) from e

    pattern.name = payload.name
    pattern.subject = payload.subject
    pattern.grade = payload.grade
    pattern.config_json = payload.config_json
    db.commit()
    db.refresh(pattern)
    return pattern


@router.delete("/{pattern_id}", status_code=204)
def delete_pattern(pattern_id: int, db: Session = Depends(get_db)):
    pattern = db.get(models.Pattern, pattern_id)
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    db.delete(pattern)
    db.commit()
