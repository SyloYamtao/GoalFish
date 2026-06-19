#!/usr/bin/env python3
"""Import cleaned player dataset CSV into Postgres."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402
from app.db.models import (  # noqa: E402
    PredictionPlayerDatasetRecord,
    PredictionPlayerRecord,
    PredictionTeamMetadataRecord,
)


REQUIRED_PLAYER_FIELDS = [
    "team_fifa",
    "team_iso3",
    "shirt_number",
    "player_name",
    "player_external_id",
    "position_primary",
    "expected_role",
    "expected_minutes_share",
    "derived_overall",
    "derived_attack",
    "derived_defense",
    "derived_pace",
    "derived_finishing",
    "derived_passing",
    "derived_set_piece",
    "derived_gk",
    "ratings_json",
]


DERIVED_FIELDS = {
    "derived_overall": "overall",
    "derived_attack": "attack",
    "derived_defense": "defense",
    "derived_pace": "pace",
    "derived_finishing": "finishing",
    "derived_passing": "passing",
    "derived_set_piece": "set_piece",
    "derived_gk": "gk",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def safe_int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def parse_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def dataset_file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_players(rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("Input player CSV is empty")
    missing_columns = [field for field in REQUIRED_PLAYER_FIELDS if field not in rows[0]]
    if missing_columns:
        raise ValueError(f"Input player CSV missing columns: {missing_columns}")

    shirt_keys = Counter()
    external_keys = Counter()
    for index, row in enumerate(rows, start=2):
        for field in REQUIRED_PLAYER_FIELDS:
            if row.get(field, "") == "":
                raise ValueError(f"Row {index} missing required field {field}")
        shirt_key = (row["team_iso3"], safe_int(row["shirt_number"]))
        shirt_keys[shirt_key] += 1
        external_key = (row["team_iso3"], row["player_external_id"])
        external_keys[external_key] += 1
        for field in DERIVED_FIELDS:
            if safe_float(row.get(field)) is None:
                raise ValueError(f"Row {index} has invalid {field}")

    duplicate_shirts = [key for key, count in shirt_keys.items() if count > 1]
    if duplicate_shirts:
        raise ValueError(f"Duplicate shirt number per team: {duplicate_shirts[:5]}")
    duplicate_external_ids = [key for key, count in external_keys.items() if key[1] and count > 1]
    if duplicate_external_ids:
        raise ValueError(f"Duplicate external id per team: {duplicate_external_ids[:5]}")


def build_player_payload(row: dict[str, str], dataset_id: str) -> dict[str, Any]:
    ratings = parse_json(row.get("ratings_json"), {})
    derived = {
        target_key: safe_float(row.get(source_key), 0.0)
        for source_key, target_key in DERIVED_FIELDS.items()
    }
    role_scores = parse_json(row.get("derived_role_scores"), {})
    if isinstance(role_scores, dict) and role_scores:
        derived["role_scores"] = role_scores
    if row.get("derived_score_source"):
        derived["score_source"] = row["derived_score_source"]
    expected_role = row.get("expected_role") or "rotation"
    metadata = {
        "club_fm": row.get("club_fm", ""),
        "club_fifa": row.get("club_fifa", ""),
        "fm_ca": safe_int(row.get("fm_ca"), 0),
        "fm_pa": safe_int(row.get("fm_pa"), 0),
        "fifa_position_class": row.get("fifa_position_class", ""),
        "caps_intl": safe_int(row.get("caps_intl"), 0),
        "goals_intl": safe_int(row.get("goals_intl"), 0),
        "birth_date": row.get("birth_date", ""),
        "market_value": row.get("market_value", ""),
        "role_basis": "ca_age_inferred",
    }
    return {
        "id": f"ply_{dataset_id}_{row['team_iso3']}_{safe_int(row['shirt_number'], 0):02d}_{row['player_external_id']}",
        "dataset_id": dataset_id,
        "team_name": row["team_fifa"],
        "team_iso3": row["team_iso3"],
        "player_external_id": row.get("player_external_id") or None,
        "full_name": row["player_name"],
        "full_name_en": row.get("player_name_en") or row["player_name"],
        "full_name_alt": [],
        "position_primary": row["position_primary"],
        "position_secondary": [],
        "age": safe_int(row.get("age")),
        "foot": row.get("foot") or None,
        "height_cm": safe_int(row.get("height_cm")),
        "ratings": ratings,
        "derived": derived,
        "availability": {"status": "available"},
        "expected_role": expected_role,
        "expected_minutes_share": safe_float(row.get("expected_minutes_share"), 0.55),
        "shirt_number": safe_int(row.get("shirt_number")),
        "position_class": row.get("fifa_position_class") or None,
        "caps_intl": safe_int(row.get("caps_intl"), 0),
        "goals_intl": safe_int(row.get("goals_intl"), 0),
        "club_fifa": row.get("club_fifa") or None,
        "player_metadata": metadata,
    }


def build_team_metadata_payload(row: dict[str, str], dataset_id: str, uid_to_player_id: dict[str, str]) -> dict[str, Any]:
    metadata_json = parse_json(row.get("metadata_json"), {})
    key_uids = parse_csv_list(row.get("key_player_uids"))
    key_player_ids = [uid_to_player_id[uid] for uid in key_uids if uid in uid_to_player_id]
    return {
        "id": f"tm_{dataset_id}_{row['team_iso3']}",
        "dataset_id": dataset_id,
        "team_fifa": row["team_fifa"],
        "team_iso3": row["team_iso3"],
        "team_zh": row.get("team_zh") or None,
        "group_label": row.get("group_label") or None,
        "head_coach": row.get("head_coach") or None,
        "formation_primary": row.get("formation_primary") or None,
        "formation_secondary": parse_csv_list(row.get("formation_secondary")),
        "tactical_style": {
            "label": row.get("tactical_label", ""),
            "description": row.get("tactical_description", ""),
            "raw_text": metadata_json.get("raw_tactics", {}),
        },
        "key_player_ids": key_player_ids,
        "squad_status": row.get("squad_status") or "final_26",
        "team_metadata": {
            **metadata_json,
            "key_player_uids": key_uids,
            "missing_key_player_uids": [uid for uid in key_uids if uid not in uid_to_player_id],
        },
    }


def ratings_schema(rows: list[dict[str, str]], normalize_strategy: str) -> dict[str, Any]:
    raw_fields = set()
    for row in rows[:50]:
        raw_fields.update(parse_json(row.get("ratings_json"), {}).keys())
    score_source = next((row.get("derived_score_source") for row in rows if row.get("derived_score_source")), None)
    return {
        "raw_fields": sorted(raw_fields),
        "normalize_strategy": normalize_strategy,
        "normalizer_version": score_source or "cleaning_rule_v2",
        "derived_fields": list(DERIVED_FIELDS.values()),
        "derived_explain_fields": ["role_scores", "score_source"],
    }


def import_dataset(
    input_path: Path,
    team_metadata_path: Path | None,
    source_kind: str,
    scope: str,
    dataset_id: str,
    normalize_strategy: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    rows = read_csv(input_path)
    validate_players(rows)
    team_rows = read_csv(team_metadata_path) if team_metadata_path else []

    player_payloads = [build_player_payload(row, dataset_id) for row in rows]
    uid_to_player_id = {
        payload["player_external_id"]: payload["id"]
        for payload in player_payloads
        if payload.get("player_external_id")
    }
    team_payloads = [
        build_team_metadata_payload(row, dataset_id, uid_to_player_id)
        for row in team_rows
    ]

    summary = {
        "dataset_id": dataset_id,
        "source_kind": source_kind,
        "scope": scope,
        "players": len(player_payloads),
        "teams": len({payload["team_iso3"] for payload in player_payloads}),
        "team_metadata": len(team_payloads),
        "input_sha256": dataset_file_hash(input_path),
    }
    if dry_run:
        return summary

    engine = create_engine(Config.DATABASE_URL, future=True, pool_pre_ping=True)
    with Session(engine) as session:
        session.execute(delete(PredictionTeamMetadataRecord).where(PredictionTeamMetadataRecord.dataset_id == dataset_id))
        session.execute(delete(PredictionPlayerRecord).where(PredictionPlayerRecord.dataset_id == dataset_id))
        session.execute(delete(PredictionPlayerDatasetRecord).where(PredictionPlayerDatasetRecord.dataset_id == dataset_id))
        session.flush()

        dataset = PredictionPlayerDatasetRecord(
            dataset_id=dataset_id,
            source_label="fifa_squad_list_v1_2026_06_12" if source_kind == "fifa_md_2026" else source_kind,
            scope_label=scope,
            ratings_schema=ratings_schema(rows, normalize_strategy),
            teams_count=summary["teams"],
            players_count=summary["players"],
            created_at=datetime.now(timezone.utc),
            dataset_metadata={
                "source_kind": source_kind,
                "normalize_strategy": normalize_strategy,
                "input_path": str(input_path),
                "team_metadata_path": str(team_metadata_path) if team_metadata_path else None,
                "input_sha256": summary["input_sha256"],
            },
        )
        session.add(dataset)
        session.flush()
        session.bulk_insert_mappings(PredictionPlayerRecord, player_payloads)
        if team_payloads:
            session.bulk_insert_mappings(PredictionTeamMetadataRecord, team_payloads)
        session.commit()

        summary["db_players"] = session.scalar(
            select(func.count()).select_from(PredictionPlayerRecord).where(PredictionPlayerRecord.dataset_id == dataset_id)
        )
        summary["db_team_metadata"] = session.scalar(
            select(func.count()).select_from(PredictionTeamMetadataRecord).where(PredictionTeamMetadataRecord.dataset_id == dataset_id)
        )
    engine.dispose()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--team-metadata")
    parser.add_argument("--source-kind", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--normalize-strategy", default="fm")
    parser.add_argument("--alias-file")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    summary = import_dataset(
        input_path=Path(args.input),
        team_metadata_path=Path(args.team_metadata) if args.team_metadata else None,
        source_kind=args.source_kind,
        scope=args.scope,
        dataset_id=args.dataset_id,
        normalize_strategy=args.normalize_strategy,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
