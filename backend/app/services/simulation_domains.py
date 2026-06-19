"""Football-only simulation domain constants and helpers."""

FOOTBALL_MATCH = "football_match"

SUPPORTED_SIMULATION_DOMAINS = {FOOTBALL_MATCH}


def normalize_simulation_domain(value: str | None) -> str:
    """Return the supported simulation domain, defaulting to football."""
    domain = str(value or "").strip().lower()
    if not domain:
        return FOOTBALL_MATCH
    if domain not in SUPPORTED_SIMULATION_DOMAINS:
        raise ValueError(f"Unsupported simulation_domain: {value}")
    return domain


def is_football_match_domain(value: str | None) -> bool:
    return normalize_simulation_domain(value) == FOOTBALL_MATCH
