from fastapi import APIRouter, UploadFile, File
from typing import Dict

from app.services.indices import get_region_indices, import_indices_csv

router = APIRouter(prefix="/api/indices")


@router.get("/regions")
def list_regions() -> Dict[str, float]:
    return get_region_indices()


@router.post("/import")
async def import_regions(file: UploadFile = File(...)) -> Dict[str, str]:
    content = (await file.read()).decode()
    import_indices_csv(content)
    return {"status": "ok"}
