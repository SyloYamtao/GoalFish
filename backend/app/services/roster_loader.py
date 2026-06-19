"""Roster loading helpers for Step2 team-strength estimation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from ..db.models import PredictionPlayerRecord, PredictionTeamMetadataRecord
from ..db.session import get_session


@dataclass
class PlayerSnapshot:
    """Snapshot of one row from prediction_player."""

    id: str
    name: str
    name_en: str
    position_primary: str
    position_class: str
    age: int
    derived: dict
    expected_role: str
    expected_minutes_share: float
    availability: dict
    shirt_number: int | None
    club_fifa: str | None

    @property
    def is_available(self) -> bool:
        return self.availability.get("status") in ("available", "doubtful")


@dataclass
class TeamRoster:
    iso3: str
    team_fifa: str
    players: list[PlayerSnapshot]

    @property
    def starters(self) -> list[PlayerSnapshot]:
        return [player for player in self.players if player.expected_role == "starter"]

    @property
    def goalkeepers(self) -> list[PlayerSnapshot]:
        return [player for player in self.players if player.position_primary == "GK"]


class RosterLoader:
    """Load immutable team roster snapshots from prediction_player."""

    def snapshot(self, dataset_id: str, home_iso3: str, away_iso3: str) -> tuple[TeamRoster, TeamRoster]:
        """Return `(home_roster, away_roster)` for a dataset and match pair."""

        with get_session() as session:
            return (
                self._load_team(session, dataset_id, _normalize_iso3(home_iso3)),
                self._load_team(session, dataset_id, _normalize_iso3(away_iso3)),
            )

    def from_snapshot(self, model_input_squads: dict) -> tuple[TeamRoster, TeamRoster]:
        """Deserialize `PredictionConfigRecord.model_input_snapshot.squads`."""

        return (
            _team_from_snapshot(model_input_squads.get("home") or {}),
            _team_from_snapshot(model_input_squads.get("away") or {}),
        )

    def to_snapshot(self, home: TeamRoster, away: TeamRoster) -> dict:
        """Serialize rosters into a deterministic model input snapshot."""

        return {
            "home": _team_to_snapshot(home),
            "away": _team_to_snapshot(away),
        }

    def _load_team(self, session: Any, dataset_id: str, iso3: str) -> TeamRoster:
        team_meta = session.scalar(
            select(PredictionTeamMetadataRecord)
            .where(PredictionTeamMetadataRecord.dataset_id == dataset_id)
            .where(PredictionTeamMetadataRecord.team_iso3 == iso3)
            .limit(1)
        )
        rows = list(
            session.scalars(
                select(PredictionPlayerRecord)
                .where(PredictionPlayerRecord.dataset_id == dataset_id)
                .where(PredictionPlayerRecord.team_iso3 == iso3)
                .order_by(
                    PredictionPlayerRecord.expected_role.asc(),
                    PredictionPlayerRecord.expected_minutes_share.desc(),
                    PredictionPlayerRecord.shirt_number.asc(),
                )
            ).all()
        )
        team_fifa = team_meta.team_fifa if team_meta else rows[0].team_name if rows else iso3
        return TeamRoster(
            iso3=iso3,
            team_fifa=team_fifa,
            players=[_player_from_record(row) for row in rows],
        )


def apply_graph_facts(roster: TeamRoster, graph_facts: Any) -> TeamRoster:
    """
    Overlay GraphFacts.player_availability onto a roster in-place.

    GraphFacts is intentionally duck-typed to keep this helper usable in tests and
    in Step2 fallback paths where graph facts may be absent.
    """

    if graph_facts is None:
        return roster

    availability_by_player = getattr(graph_facts, "player_availability", {}) or {}
    for player in roster.players:
        graph_availability = availability_by_player.get(player.id)
        if graph_availability is None:
            continue
        player.availability = _availability_to_dict(graph_availability)
    return roster


def apply_source_availability(
    roster: TeamRoster,
    source_text: str | None,
    *,
    evidence_type: str = "source_document",
) -> TeamRoster:
    """Overlay player-level availability mentioned in the uploaded source text."""

    text = str(source_text or "")
    if not text.strip():
        return roster

    clauses = [
        clause
        for line in re.split(r"[\n\r]+", text)
        for clause in _availability_clauses(line)
    ]
    for player in roster.players:
        variants = _player_name_variants(player)
        if not variants:
            continue
        for clause in clauses:
            status = _availability_status_from_line(clause)
            if not status or not _line_mentions_player(clause, variants):
                continue
            _merge_player_availability(
                player,
                status,
                {
                    "type": evidence_type,
                    "id": f"{evidence_type}:{roster.iso3}:{player.id}",
                    "summary": clause[:300],
                },
            )
            break
    return roster


def _player_from_record(row: PredictionPlayerRecord) -> PlayerSnapshot:
    return PlayerSnapshot(
        id=row.id,
        name=row.full_name,
        name_en=row.full_name_en or row.full_name,
        position_primary=row.position_primary,
        position_class=row.position_class or _position_class(row.position_primary),
        age=int(row.age or 0),
        derived=dict(row.derived or {}),
        expected_role=row.expected_role or "rotation",
        expected_minutes_share=float(row.expected_minutes_share or 0),
        availability=dict(row.availability or {"status": "available"}),
        shirt_number=row.shirt_number,
        club_fifa=row.club_fifa,
    )


def _team_to_snapshot(roster: TeamRoster) -> dict:
    return {
        "team_name": roster.team_fifa,
        "team_iso3": roster.iso3,
        "starter_ids": [player.id for player in roster.players if player.expected_role == "starter"],
        "bench_ids": [player.id for player in roster.players if player.expected_role == "bench"],
        "reserve_ids": [player.id for player in roster.players if player.expected_role == "reserve"],
        "players": [_player_to_snapshot(player) for player in roster.players],
        "stats": _team_stats(roster),
    }


def _team_from_snapshot(payload: dict) -> TeamRoster:
    players = [_player_from_snapshot(player) for player in payload.get("players") or []]
    return TeamRoster(
        iso3=_normalize_iso3(payload.get("team_iso3") or payload.get("iso3") or ""),
        team_fifa=payload.get("team_name") or payload.get("team_fifa") or "",
        players=players,
    )


def _player_to_snapshot(player: PlayerSnapshot) -> dict:
    return {
        "id": player.id,
        "name": player.name,
        "name_en": player.name_en,
        "position_primary": player.position_primary,
        "position_class": player.position_class,
        "age": player.age,
        "derived": dict(player.derived or {}),
        "expected_role": player.expected_role,
        "expected_minutes_share": player.expected_minutes_share,
        "availability": dict(player.availability or {"status": "available"}),
        "shirt_number": player.shirt_number,
        "club_fifa": player.club_fifa,
    }


def _player_from_snapshot(payload: dict) -> PlayerSnapshot:
    position = payload.get("position_primary") or payload.get("position") or ""
    return PlayerSnapshot(
        id=str(payload.get("id") or ""),
        name=payload.get("name") or payload.get("full_name") or "",
        name_en=payload.get("name_en") or payload.get("full_name_en") or payload.get("name") or "",
        position_primary=position,
        position_class=payload.get("position_class") or _position_class(position),
        age=int(payload.get("age") or 0),
        derived=dict(payload.get("derived") or {}),
        expected_role=payload.get("expected_role") or "rotation",
        expected_minutes_share=float(payload.get("expected_minutes_share") or 0),
        availability=dict(payload.get("availability") or {"status": "available"}),
        shirt_number=payload.get("shirt_number"),
        club_fifa=payload.get("club_fifa"),
    )


def _team_stats(roster: TeamRoster) -> dict:
    players = roster.players
    return {
        "avg_overall": _avg(player.derived.get("overall") for player in players),
        "avg_attack": _avg(player.derived.get("attack") for player in players),
        "avg_defense": _avg(player.derived.get("defense") for player in players),
        "gk_overall": _avg(player.derived.get("gk") for player in roster.goalkeepers),
        "available": sum(1 for player in players if player.availability.get("status") == "available"),
        "doubtful": sum(1 for player in players if player.availability.get("status") == "doubtful"),
        "injured": sum(1 for player in players if player.availability.get("status") == "injured"),
        "suspended": sum(1 for player in players if player.availability.get("status") == "suspended"),
    }


def _avg(values: Any) -> float | None:
    numeric = [float(value) for value in values if value is not None]
    if not numeric:
        return None
    return round(sum(numeric) / len(numeric), 2)


def _availability_to_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return dict(value)
    return {
        "status": getattr(value, "status", "available"),
        "return_date": getattr(value, "return_date", None),
        "evidence_refs": list(getattr(value, "evidence_refs", []) or []),
    }


_AVAILABILITY_PRIORITY = {
    "available": 0,
    "doubtful": 1,
    "injured": 2,
    "suspended": 3,
}

_SUSPENDED_PATTERN = re.compile(r"停赛|红牌停赛|suspended|suspension|\bban(?:ned)?\b", re.I)
_INJURED_PATTERN = re.compile(r"因伤缺席|伤缺|受伤|injured|out with injury", re.I)
_DOUBTFUL_PATTERN = re.compile(r"出战成疑|存疑|doubtful|questionable", re.I)
_NEGATED_AVAILABILITY_PATTERN = re.compile(
    r"暂无|未见|未找到|无可靠|无确认|没有|无(?:[^，,。；;|]{0,16})?(?:伤病|停赛)|"
    r"不(?:在停赛名单|受停赛影响|影响)|本人不受|not confirmed|no reliable|"
    r"no confirmed|not suspended|not injured|no injuries?|no suspensions?",
    re.I,
)


def _availability_status_from_line(line: str) -> str | None:
    if _NEGATED_AVAILABILITY_PATTERN.search(line):
        return None
    if _SUSPENDED_PATTERN.search(line):
        return "suspended"
    if _INJURED_PATTERN.search(line):
        return "injured"
    if _DOUBTFUL_PATTERN.search(line):
        return "doubtful"
    return None


def _availability_clauses(line: str) -> list[str]:
    return [
        clause.strip()
        for clause in re.split(r"[|。；;，,]+", str(line or ""))
        if clause.strip()
    ]


def _player_name_variants(player: PlayerSnapshot) -> list[str]:
    names = {
        str(player.name or "").strip(),
        str(player.name_en or "").strip(),
    }
    variants: set[str] = set()
    for name in names:
        if not name:
            continue
        variants.add(name.casefold())
        parts = [part for part in re.split(r"[\s/·.'-]+", name) if part]
        if len(parts) >= 2 and len(parts[-1]) >= 4:
            variants.add(parts[-1].casefold())
    return sorted(variants, key=len, reverse=True)


def _line_mentions_player(line: str, variants: list[str]) -> bool:
    normalized = line.casefold()
    status_spans = [
        match.span()
        for pattern in (_SUSPENDED_PATTERN, _INJURED_PATTERN, _DOUBTFUL_PATTERN)
        for match in pattern.finditer(line)
    ]
    if not status_spans:
        return False
    for variant in variants:
        if " " in variant:
            start = normalized.find(variant)
            while start != -1:
                end = start + len(variant)
                if any(_is_near_status(line, start, end, status_start, status_end) for status_start, status_end in status_spans):
                    return True
                start = normalized.find(variant, start + 1)
            continue
        for match in re.finditer(rf"(?<![a-z]){re.escape(variant)}(?![a-z])", normalized):
            if any(_is_near_status(line, match.start(), match.end(), status_start, status_end) for status_start, status_end in status_spans):
                return True
    return False


def _merge_player_availability(player: PlayerSnapshot, status: str, evidence_ref: dict[str, Any]) -> None:
    availability = dict(player.availability or {"status": "available"})
    current_status = str(availability.get("status") or "available")
    if _AVAILABILITY_PRIORITY.get(status, 0) >= _AVAILABILITY_PRIORITY.get(current_status, 0):
        availability["status"] = status
        availability.setdefault("return_date", None)

    refs = list(availability.get("evidence_refs") or [])
    if evidence_ref not in refs:
        refs.append(evidence_ref)
    availability["evidence_refs"] = refs
    player.availability = availability


def _is_near_status(text: str, name_start: int, name_end: int, status_start: int, status_end: int) -> bool:
    if name_end <= status_start:
        bridge = text[name_end:status_start]
        if re.search(r"替代|替换|顶替|replace|replaces?|instead of|不在|不受|无", bridge, re.I):
            return False
        return (status_start - name_end) <= 24
    if status_end <= name_start:
        bridge = text[status_end:name_start]
        if re.search(r"迫使|导致|削弱|替代|替换|顶替|replace|forces?|means", bridge, re.I):
            return False
        return bool(re.fullmatch(r"\s*(?:球员|players?)?\s*(?:[：:,-]|的)?\s*", bridge, re.I))
    return True


def _position_class(position: str) -> str:
    if position == "GK":
        return "GK"
    if position in {"CB", "FB"}:
        return "DF"
    if position in {"DM", "CM", "AM"}:
        return "MF"
    if position in {"WG", "ST"}:
        return "FW"
    return ""


def _normalize_iso3(value: str) -> str:
    return (value or "").strip().upper()
