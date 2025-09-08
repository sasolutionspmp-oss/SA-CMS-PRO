"""Pricing utilities."""

def estimate_cost(tokens: int, rate: float = 0.01) -> float:
    return round(tokens * rate, 2)
