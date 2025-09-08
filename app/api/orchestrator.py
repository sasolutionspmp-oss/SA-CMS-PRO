from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, List, Dict

router = APIRouter(prefix="/api/orchestrator")


class OrchestratorRequest(BaseModel):
    projectId: Optional[str] = None
    zipJobId: Optional[str] = None


@router.post("/run")
async def run_orchestrator(req: OrchestratorRequest) -> Dict:
    identifier = req.projectId or req.zipJobId or "unknown"
    return {
        "scope_summary": f"Summary for project {identifier}",
        "constraints": ["schedule"],
        "risks": ["budget"],
        "missing_info": ["site photos"],
        "vendor_questions": ["Any preferred vendors?"],
        "draft_line_items": [
            {"desc": "Sample line item", "qty": 1, "unit": "ea"}
        ],
    }
