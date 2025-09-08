from typing import Dict, Optional

from .indices import get_region_indices
from .rsmeans_import import get_item


def suggest_unit_cost(
    desc: str,
    region: str,
    vendor_multipliers: Optional[Dict[str, float]] = None,
    code: Optional[str] = None,
) -> float:
    """Suggest a unit cost using region factors, vendor multipliers and RSMeans data."""
    base_cost = 10.0
    if code:
        item = get_item(code)
        if item:
            base_cost = float(item.get("base_cost", base_cost))
    region_factor = get_region_indices().get(region.lower(), 1.0)
    vendor_factor = 1.0
    if vendor_multipliers:
        vendor_factor = sum(vendor_multipliers.values()) / len(vendor_multipliers)
    return base_cost * region_factor * vendor_factor
