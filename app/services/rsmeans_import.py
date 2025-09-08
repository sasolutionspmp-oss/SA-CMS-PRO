import csv
from io import StringIO
from typing import Dict

# In-memory RSMeans-like dataset
_RS_MEANS: Dict[str, Dict[str, str]] = {}

def import_rsmeans_csv(content: str) -> None:
    """Import RSMeans-like data from CSV content.

    Expected columns: code, desc, unit, base_cost
    """
    reader = csv.DictReader(StringIO(content))
    for row in reader:
        code = row.get("code")
        desc = row.get("desc")
        unit = row.get("unit")
        cost_str = row.get("base_cost")
        if not code or not cost_str:
            continue
        try:
            cost = float(cost_str)
        except ValueError:
            continue
        _RS_MEANS[code] = {"desc": desc or "", "unit": unit or "", "base_cost": cost}

def get_item(code: str) -> Dict[str, str]:
    return _RS_MEANS.get(code, {})
