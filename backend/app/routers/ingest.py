"""Document ingestion router."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/", response_model=schemas.DocumentRead)
def ingest_document(
    doc: schemas.DocumentCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> models.Document:
    db_doc = models.Document(content=doc.content)
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)
    return db_doc
