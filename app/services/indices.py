import csv
from io import StringIO
from typing import Dict

# In-memory region indices store seeded with synthetic regions
_REGION_INDICES: Dict[str, float] = {
    "north": 1.0,
    "south": 1.2,
    "east": 0.9,
    "west": 1.1,
}

def get_region_indices() -> Dict[str, float]:
    """Return current region cost indices."""
    return dict(_REGION_INDICES)

def import_indices_csv(content: str) -> None:
    """Import region indices from CSV content.

    Expected columns: region/name, factor/index
    """
    reader = csv.DictReader(StringIO(content))
    for row in reader:
        name = row.get("region") or row.get("name")
        if not name:
            continue
        factor_str = row.get("factor") or row.get("index")
        try:
            factor = float(factor_str) if factor_str is not None else 1.0
        except ValueError:
            factor = 1.0
        _REGION_INDICES[name.strip().lower()] = factor
