from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Optional

from app.services import pricing

router = APIRouter(prefix="/api/estimate")


class LineItem(BaseModel):
    desc: str
    qty: float
    unit: str
    unit_cost: Optional[float] = None
    code: Optional[str] = None


class EstimateRequest(BaseModel):
    lines: List[LineItem]
    overhead_pct: float
    margin_pct: float
    region: str
    vendorMultipliers: Dict[str, float] = {}


_ESTIMATES: List[Dict] = []


@router.post("/calc")
def calc_estimate(req: EstimateRequest) -> Dict:
    lines_out = []
    subtotal = 0.0
    for line in req.lines:
        cost = line.unit_cost or pricing.suggest_unit_cost(
            line.desc, req.region, req.vendorMultipliers, line.code
        )
        line_total = line.qty * cost
        lines_out.append(
            {
                "desc": line.desc,
                "qty": line.qty,
                "unit": line.unit,
                "unit_cost": cost,
                "line_total": line_total,
            }
        )
        subtotal += line_total
    overhead = subtotal * req.overhead_pct / 100.0
    margin = (subtotal + overhead) * req.margin_pct / 100.0
    total = subtotal + overhead + margin
    result = {
        "lines": lines_out,
        "subtotal": subtotal,
        "overhead": overhead,
        "margin": margin,
        "total": total,
    }
    _ESTIMATES.append(result)
    return result
