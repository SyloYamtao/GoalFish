import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.clean_fm_wc2026 import (  # noqa: E402
    get_candidates_for_md_team,
    match_with_tiebreaker,
    normalize,
    three_tier_match,
    token_set,
)


def test_normalize_removes_accents():
    assert normalize("Matej Kovář") == normalize("Matej Kovar")


def test_normalize_lastname_first_vs_firstname_first():
    md = normalize("KOVAR Matej")
    csv = normalize("Matej Kovář")
    assert token_set(md) == token_set(csv)


def test_tier1_exact_match():
    md = "MESSI Lionel"
    csv_candidates = [
        {"name": "Lionel Andrés Messi Cuccittini", "uid": "30001514"},
        {"name": "Lionel Martinez", "uid": "40002000"},
    ]
    match = three_tier_match(md, csv_candidates)
    assert match["uid"] == "30001514"


def test_tie_breaker_by_club():
    md = {"name": "MARTINEZ Lionel", "club": "Inter Miami"}
    csv_candidates = [
        {"name": "Lionel Martinez", "club": "Inter Miami", "uid": "A"},
        {"name": "Lionel Martinez", "club": "Barcelona", "uid": "B"},
    ]
    match = match_with_tiebreaker(md, csv_candidates)
    assert match["uid"] == "A"


def test_ambiguous_when_all_tiebreaker_fail():
    md = {"name": "SMITH John", "club": "Unknown", "age": 25}
    csv_candidates = [
        {"name": "John Smith", "club": "Unknown", "age": 24, "ca": 120, "uid": "A"},
        {"name": "John Smith", "club": "Unknown", "age": 26, "ca": 121, "uid": "B"},
    ]
    match = match_with_tiebreaker(md, csv_candidates)
    assert match["status"] == "ambiguous"
    assert "A" in match["candidates"] and "B" in match["candidates"]


def test_dual_nationality_candidate_pool():
    md_team = "SWE"
    csv_rows = [
        {"name": "Player A", "nationality": "England,Sweden", "uid": "1"},
        {"name": "Player B", "nationality": "Sweden", "uid": "2"},
        {"name": "Player C", "nationality": "Norway", "uid": "3"},
    ]
    candidates = get_candidates_for_md_team(md_team, csv_rows)
    assert len(candidates) == 2
    assert "3" not in [c["uid"] for c in candidates]
