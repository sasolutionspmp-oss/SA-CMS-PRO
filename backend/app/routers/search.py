"""Document search router."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/", response_model=list[schemas.DocumentRead])
def search_documents(
    q: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
) -> list[models.Document]:
    return db.query(models.Document).filter(models.Document.content.contains(q)).all()
