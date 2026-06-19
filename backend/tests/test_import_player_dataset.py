import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_player_dataset import (  # noqa: E402
    build_player_payload,
    parse_csv_list,
    validate_players,
)


def _player(**overrides):
    row = {
        "team_fifa": "Brazil",
        "team_iso3": "BRA",
        "shirt_number": "10",
        "player_name": "Neymar",
        "player_name_en": "Neymar",
        "player_external_id": "19024412",
        "fifa_position_class": "FW",
        "position_primary": "ST",
        "age": "34",
        "fm_ca": "160",
        "fm_pa": "190",
        "club_fm": "SAN",
        "club_fifa": "Santos FC",
        "height_cm": "175",
        "foot": "R",
        "expected_role": "starter",
        "expected_minutes_share": "0.95",
        "caps_intl": "130",
        "goals_intl": "80",
        "derived_overall": "80.0",
        "derived_attack": "85.5",
        "derived_defense": "20.0",
        "derived_pace": "80.0",
        "derived_finishing": "88.0",
        "derived_passing": "82.0",
        "derived_set_piece": "90.0",
        "derived_gk": "0",
        "derived_role_scores": json.dumps({"shooting": 88.0, "movement": 84.0}),
        "derived_score_source": "attribute_role_weight_v1",
        "ratings_json": json.dumps({"fm_ca": 160, "club": "SAN"}),
    }
    row.update(overrides)
    return row


def test_build_player_payload_keeps_fifa_fields_and_derived():
    payload = build_player_payload(_player(), "wc2026_fifa_v1")

    assert payload["dataset_id"] == "wc2026_fifa_v1"
    assert payload["team_name"] == "Brazil"
    assert payload["derived"]["overall"] == 80.0
    assert payload["derived"]["role_scores"]["shooting"] == 88.0
    assert payload["derived"]["score_source"] == "attribute_role_weight_v1"
    assert payload["shirt_number"] == 10
    assert payload["caps_intl"] == 130
    assert payload["player_metadata"]["club_fm"] == "SAN"
    assert payload["player_metadata"]["role_basis"] == "ca_age_inferred"


def test_validate_players_rejects_duplicate_shirt_number():
    rows = [_player(), _player(player_external_id="other")]

    with pytest.raises(ValueError, match="Duplicate shirt number"):
        validate_players(rows)


def test_validate_players_rejects_missing_derived():
    rows = [_player(derived_overall="")]

    with pytest.raises(ValueError, match="derived_overall"):
        validate_players(rows)


def test_parse_csv_list():
    assert parse_csv_list("3-5-2,4-2-3-1") == ["3-5-2", "4-2-3-1"]
    assert parse_csv_list("") == []
