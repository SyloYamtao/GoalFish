"""
Step2 图谱事实查询封装。

该服务只读 Step1 图谱事实，将球员伤病/停赛/状态新闻与球队近期状态
整理为 Step2 可直接消费的 GraphFacts。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import desc, select

from ..db.models import PredictionPlayerRecord
from ..db.session import get_session
from ..utils.logger import get_logger


logger = get_logger("goalfish.graph_evidence_query")

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except ImportError:  # pragma: no cover - optional dependency fallback.
    _rapidfuzz_fuzz = None


@dataclass
class PlayerAvailability:
    status: str
    return_date: str | None = None
    evidence_refs: list[dict] = field(default_factory=list)


@dataclass
class GraphFacts:
    """Step2 准备时一次性查出的所有图谱事实。"""

    player_availability: dict[str, PlayerAvailability] = field(default_factory=dict)
    team_recent_form: dict[str, list[dict]] = field(default_factory=dict)
    team_news: dict[str, list[dict]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    player_team_iso3: dict[str, str] = field(default_factory=dict)

    def has_facts_for_team(self, iso3: str) -> bool:
        team_iso3 = _normalize_iso3(iso3)
        if self.team_news.get(team_iso3) or self.team_recent_form.get(team_iso3):
            return True

        for player_id, availability in self.player_availability.items():
            if self.player_team_iso3.get(player_id) != team_iso3:
                continue
            if availability.status != "available" or availability.evidence_refs:
                return True
        return False


@dataclass
class _GraphSnapshot:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    node_map: dict[str, dict[str, Any]]


class GraphEvidenceQuery:
    """见 realistic-step2-step3/03-player-dataset.md § 3.7。"""

    MAX_PLAYERS_PER_TEAM = 30
    MAX_NEIGHBORS_PER_NODE = 12
    MAX_TOTAL_NODES = 200

    PLAYER_EDGE_TYPES = ("has_news", "injury", "suspension", "form_event")
    TWO_HOP_EDGE_TYPES = ("plays_for", "recent_form")
    STATUS_PRIORITY = {
        "available": 0,
        "doubtful": 1,
        "injured": 2,
        "suspended": 3,
    }

    def __init__(self, graphiti_client: Any = None):
        """graphiti_client 可注入；默认从 graph_backend_factory 拿 reader。"""

        self._graphiti_client = graphiti_client

    def for_match(
        self,
        *,
        home_iso3: str,
        away_iso3: str,
        graph_id: str,
        dataset_id: str,
    ) -> GraphFacts:
        """一次性查询双方所有名单球员的图谱邻居。"""

        facts = GraphFacts()
        try:
            client = self._resolve_graph_client()
            snapshot = self._load_graph_snapshot(client, graph_id)
        except Exception as exc:  # noqa: BLE001 - graph backend failure must be fail-open here.
            logger.warning("图谱事实查询失败: %s", exc)
            facts.warnings.append("graph_unreachable")
            self._try_add_default_availability(facts, dataset_id, home_iso3, away_iso3)
            return facts

        players = self._load_match_players(facts, dataset_id, home_iso3, away_iso3)

        resolved_nodes: dict[str, dict[str, Any]] = {}
        total_neighbors_seen = 0
        for player in players:
            node = self._resolve_player_node(player, snapshot.nodes)
            if not node:
                continue
            resolved_nodes[_player_id(player)] = node

            remaining_budget = self.MAX_TOTAL_NODES - total_neighbors_seen
            if remaining_budget <= 0:
                break
            limit = min(self.MAX_NEIGHBORS_PER_NODE, remaining_budget)
            neighbors = self._fetch_neighbors(client, node, snapshot, limit, facts)
            total_neighbors_seen += len(neighbors)
            self._merge_player_neighbors(facts, player, neighbors)

        for player in self._pick_top_players(players, 6):
            remaining_budget = self.MAX_TOTAL_NODES - total_neighbors_seen
            if remaining_budget <= 0:
                break
            node = resolved_nodes.get(_player_id(player))
            if not node:
                continue
            form_nodes = self._fetch_2hop_recent_form(client, node, snapshot, remaining_budget, facts)
            total_neighbors_seen += len(form_nodes)
            self._merge_recent_form(facts, player, form_nodes)

        return facts

    def _load_match_players(
        self,
        facts: GraphFacts,
        dataset_id: str,
        home_iso3: str,
        away_iso3: str,
    ) -> list[Any]:
        home_squad = self._limit_squad(self._load_squad(dataset_id, home_iso3))
        away_squad = self._limit_squad(self._load_squad(dataset_id, away_iso3))
        players = [*home_squad, *away_squad]
        for player in players:
            self._ensure_default_availability(facts, player)
        return players

    def _try_add_default_availability(
        self,
        facts: GraphFacts,
        dataset_id: str,
        home_iso3: str,
        away_iso3: str,
    ) -> None:
        try:
            self._load_match_players(facts, dataset_id, home_iso3, away_iso3)
        except Exception as exc:  # noqa: BLE001 - graph failure path should not be blocked by DB config.
            logger.warning("图谱不可用时加载球员默认 availability 失败: %s", exc)

    def _load_squad(self, dataset_id: str, team_iso3: str) -> list[PredictionPlayerRecord]:
        stmt = (
            select(PredictionPlayerRecord)
            .where(PredictionPlayerRecord.dataset_id == dataset_id)
            .where(PredictionPlayerRecord.team_iso3 == _normalize_iso3(team_iso3))
            .order_by(desc(PredictionPlayerRecord.expected_minutes_share))
            .limit(self.MAX_PLAYERS_PER_TEAM)
        )
        with get_session() as session:
            return list(session.scalars(stmt).all())

    def _limit_squad(self, squad: list[Any]) -> list[Any]:
        return list(squad)[: self.MAX_PLAYERS_PER_TEAM]

    def _resolve_graph_client(self) -> Any:
        if self._graphiti_client is None:
            from .graph_backend_factory import get_entity_reader

            return get_entity_reader()

        if callable(self._graphiti_client) and not _has_explicit_client_api(self._graphiti_client):
            return self._graphiti_client()
        return self._graphiti_client

    def _load_graph_snapshot(self, client: Any, graph_id: str) -> _GraphSnapshot:
        nodes = [_node_to_dict(node) for node in client.get_all_nodes(graph_id)]
        edges = []
        if _has_explicit_method(client, "get_all_edges"):
            edges = [_edge_to_dict(edge) for edge in client.get_all_edges(graph_id)]

        node_map = {
            node_id: node
            for node in nodes
            if (node_id := _node_id(node))
        }
        return _GraphSnapshot(nodes=nodes, edges=edges, node_map=node_map)

    def _resolve_player_node(self, player: Any, nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
        player_nodes = [node for node in nodes if _is_player_node(node)]
        if not player_nodes:
            player_nodes = nodes

        external_id = _clean_str(getattr(player, "player_external_id", None))
        if external_id:
            for node in player_nodes:
                if _clean_str(_node_external_id(node)) == external_id:
                    return node

        team_iso3 = _normalize_iso3(getattr(player, "team_iso3", ""))
        full_name_en = _clean_str(getattr(player, "full_name_en", None))
        if full_name_en:
            for node in player_nodes:
                if _node_team_iso3(node) == team_iso3 and _same_name(_node_name(node), full_name_en):
                    return node

        full_name_zh = _clean_str(getattr(player, "full_name", None))
        if full_name_zh:
            for node in player_nodes:
                if _node_team_iso3(node) == team_iso3 and _same_name(_node_name(node), full_name_zh):
                    return node

        names = _player_names(player)
        best_node = None
        best_score = 0.0
        for node in player_nodes:
            if _node_team_iso3(node) != team_iso3:
                continue
            node_name = _node_name(node)
            for name in names:
                score = _similarity(node_name, name)
                if score > best_score:
                    best_score = score
                    best_node = node

        return best_node if best_score >= 95.0 else None

    def _fetch_neighbors(
        self,
        client: Any,
        node: dict[str, Any],
        snapshot: _GraphSnapshot,
        limit: int,
        facts: GraphFacts,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        if _has_explicit_method(client, "fetch_neighbors"):
            try:
                neighbors = client.fetch_neighbors(
                    node,
                    edge_types=list(self.PLAYER_EDGE_TYPES),
                    limit=limit,
                )
            except Exception as exc:  # noqa: BLE001 - tolerate per spec §3.7.3.
                logger.warning("图谱邻居查询失败: %s", exc)
                facts.warnings.append("graph_schema_mismatch:fetch_neighbors")
                return []
            return [_node_to_dict(neighbor) for neighbor in list(neighbors)[:limit]]

        node_uuid = _node_id(node)
        if not node_uuid:
            return []

        neighbors: list[dict[str, Any]] = []
        for edge in snapshot.edges:
            if not _edge_connects_node(edge, node_uuid):
                continue
            edge_type = _edge_type(edge)
            if not _edge_type_allowed(edge_type, self.PLAYER_EDGE_TYPES):
                if edge_type and not _edge_type_allowed(edge_type, self.TWO_HOP_EDGE_TYPES):
                    _append_warning_once(facts, f"graph_schema_mismatch:{edge_type}")
                continue
            other_uuid = _edge_other_node_uuid(edge, node_uuid)
            neighbor = snapshot.node_map.get(other_uuid)
            if not neighbor:
                continue
            enriched = dict(neighbor)
            enriched["_edge_type"] = edge_type
            enriched["_edge_fact"] = _clean_str(edge.get("fact"))
            neighbors.append(enriched)
            if len(neighbors) >= limit:
                break
        return neighbors

    def _fetch_2hop_recent_form(
        self,
        client: Any,
        node: dict[str, Any],
        snapshot: _GraphSnapshot,
        limit: int,
        facts: GraphFacts,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        if _has_explicit_method(client, "fetch_2hop"):
            try:
                form_nodes = client.fetch_2hop(node, list(self.TWO_HOP_EDGE_TYPES))
            except Exception as exc:  # noqa: BLE001 - tolerate per spec §3.7.3.
                logger.warning("图谱 2-hop 查询失败: %s", exc)
                _append_warning_once(facts, "graph_schema_mismatch:recent_form")
                return []
            return [_node_to_dict(form_node) for form_node in list(form_nodes)[:limit]]

        player_uuid = _node_id(node)
        if not player_uuid:
            return []

        club_uuids: set[str] = set()
        for edge in snapshot.edges:
            if not _edge_connects_node(edge, player_uuid):
                continue
            if _edge_type_allowed(_edge_type(edge), ("plays_for",)):
                club_uuid = _edge_other_node_uuid(edge, player_uuid)
                if club_uuid:
                    club_uuids.add(club_uuid)

        form_nodes: list[dict[str, Any]] = []
        for edge in snapshot.edges:
            edge_type = _edge_type(edge)
            if not _edge_type_allowed(edge_type, ("recent_form",)):
                continue
            source_uuid = _clean_str(edge.get("source_node_uuid"))
            target_uuid = _clean_str(edge.get("target_node_uuid"))
            if source_uuid in club_uuids:
                form_uuid = target_uuid
            elif target_uuid in club_uuids:
                form_uuid = source_uuid
            else:
                continue
            form_node = snapshot.node_map.get(form_uuid)
            if not form_node:
                continue
            enriched = dict(form_node)
            enriched["_edge_type"] = edge_type
            enriched["_edge_fact"] = _clean_str(edge.get("fact"))
            form_nodes.append(enriched)
            if len(form_nodes) >= limit:
                break
        return form_nodes

    def _merge_player_neighbors(
        self,
        facts: GraphFacts,
        player: Any,
        neighbors: list[dict[str, Any]],
    ) -> None:
        player_id = _player_id(player)
        team_iso3 = _normalize_iso3(getattr(player, "team_iso3", ""))
        availability = facts.player_availability[player_id]

        for neighbor in neighbors:
            node_type = _node_type(neighbor)
            edge_type = _clean_str(neighbor.get("_edge_type")).lower()

            status = self._status_from_neighbor(neighbor, edge_type)
            if status:
                self._apply_availability(availability, status, neighbor)

            if node_type == "news" or edge_type == "has_news":
                facts.team_news.setdefault(team_iso3, []).append(_fact_ref(neighbor, player_id=player_id))
            elif node_type in {"form_event", "recent_form"} or edge_type == "form_event":
                facts.team_recent_form.setdefault(team_iso3, []).append(_fact_ref(neighbor, player_id=player_id))

    def _merge_recent_form(
        self,
        facts: GraphFacts,
        player: Any,
        form_nodes: list[dict[str, Any]],
    ) -> None:
        if not form_nodes:
            return
        player_id = _player_id(player)
        team_iso3 = _normalize_iso3(getattr(player, "team_iso3", ""))
        facts.team_recent_form.setdefault(team_iso3, []).extend(
            _fact_ref(node, player_id=player_id) for node in form_nodes
        )

    def _status_from_neighbor(self, node: dict[str, Any], edge_type: str) -> str | None:
        node_type = _node_type(node)
        if node_type == "suspension" or edge_type == "suspension":
            return "suspended"
        if node_type == "injury" or edge_type == "injury":
            return "injured"
        if node_type == "news" or edge_type == "has_news":
            text = " ".join(
                [
                    _clean_str(_node_attributes(node).get("sentiment")),
                    _node_summary(node),
                    _node_name(node),
                ]
            ).lower()
            if any(token in text for token in ("伤", "injury", "doubt")):
                return "doubtful"
        return None

    def _apply_availability(
        self,
        availability: PlayerAvailability,
        status: str,
        evidence_node: dict[str, Any],
    ) -> None:
        current_priority = self.STATUS_PRIORITY.get(availability.status, 0)
        new_priority = self.STATUS_PRIORITY.get(status, 0)
        evidence_ref = _evidence_ref(evidence_node)

        if evidence_ref not in availability.evidence_refs:
            availability.evidence_refs.append(evidence_ref)

        if new_priority >= current_priority:
            availability.status = status
            return_date = _return_date(evidence_node)
            if return_date:
                availability.return_date = return_date

    def _ensure_default_availability(self, facts: GraphFacts, player: Any) -> None:
        player_id = _player_id(player)
        facts.player_team_iso3[player_id] = _normalize_iso3(getattr(player, "team_iso3", ""))
        if player_id in facts.player_availability:
            return

        raw_availability = getattr(player, "availability", None) or {}
        status = raw_availability.get("status") if isinstance(raw_availability, dict) else None
        facts.player_availability[player_id] = PlayerAvailability(status=status or "available")

    def _pick_top_players(self, players: list[Any], limit: int) -> list[Any]:
        return sorted(players, key=_player_overall_sort_key, reverse=True)[:limit]


def _has_explicit_client_api(value: Any) -> bool:
    return any(
        _has_explicit_method(value, method_name)
        for method_name in ("get_all_nodes", "get_all_edges", "get_node_edges", "fetch_neighbors", "fetch_2hop")
    )


def _has_explicit_method(value: Any, method_name: str) -> bool:
    if method_name in getattr(value, "__dict__", {}):
        return True
    if callable(getattr(type(value), method_name, None)):
        return True
    mock_children = getattr(value, "_mock_children", {})
    return method_name in mock_children


def _node_to_dict(node: Any) -> dict[str, Any]:
    if isinstance(node, dict):
        result = dict(node)
    else:
        result = {
            "uuid": getattr(node, "uuid", None) or getattr(node, "uuid_", None) or getattr(node, "id", None),
            "name": getattr(node, "name", "") or "",
            "labels": getattr(node, "labels", []) or [],
            "summary": getattr(node, "summary", "") or "",
            "attributes": getattr(node, "attributes", {}) or {},
        }
    result.setdefault("labels", [])
    result.setdefault("attributes", {})
    result.setdefault("summary", "")
    result.setdefault("name", "")
    return result


def _edge_to_dict(edge: Any) -> dict[str, Any]:
    if isinstance(edge, dict):
        result = dict(edge)
    else:
        result = {
            "uuid": getattr(edge, "uuid", None) or getattr(edge, "uuid_", None) or getattr(edge, "id", None),
            "name": getattr(edge, "name", "") or "",
            "fact": getattr(edge, "fact", "") or "",
            "source_node_uuid": getattr(edge, "source_node_uuid", "") or "",
            "target_node_uuid": getattr(edge, "target_node_uuid", "") or "",
            "attributes": getattr(edge, "attributes", {}) or {},
        }
    result.setdefault("name", "")
    result.setdefault("fact", "")
    result.setdefault("attributes", {})
    return result


def _node_id(node: dict[str, Any]) -> str:
    return _clean_str(node.get("uuid") or node.get("id") or node.get("node_id"))


def _node_name(node: dict[str, Any]) -> str:
    return _clean_str(node.get("name") or _node_attributes(node).get("name"))


def _node_summary(node: dict[str, Any]) -> str:
    return _clean_str(node.get("summary") or node.get("_edge_fact") or _node_name(node))


def _node_attributes(node: dict[str, Any]) -> dict[str, Any]:
    attrs = node.get("attributes") or {}
    return attrs if isinstance(attrs, dict) else {}


def _node_metadata(node: dict[str, Any]) -> dict[str, Any]:
    direct = node.get("metadata")
    if isinstance(direct, dict):
        return direct
    nested = _node_attributes(node).get("metadata")
    return nested if isinstance(nested, dict) else {}


def _node_external_id(node: dict[str, Any]) -> str:
    attrs = _node_attributes(node)
    metadata = _node_metadata(node)
    return _clean_str(
        metadata.get("external_id")
        or metadata.get("player_external_id")
        or attrs.get("external_id")
        or attrs.get("player_external_id")
        or node.get("external_id")
        or node.get("player_external_id")
    )


def _node_team_iso3(node: dict[str, Any]) -> str:
    attrs = _node_attributes(node)
    metadata = _node_metadata(node)
    return _normalize_iso3(
        metadata.get("team_iso3")
        or attrs.get("team_iso3")
        or attrs.get("iso3")
        or node.get("team_iso3")
        or node.get("iso3")
    )


def _node_type(node: dict[str, Any]) -> str:
    attrs = _node_attributes(node)
    raw_type = node.get("type") or attrs.get("type") or attrs.get("entity_type")
    if raw_type:
        return _canonical_type(raw_type)

    labels = node.get("labels") or []
    for label in labels:
        normalized = _canonical_type(label)
        if normalized not in {"entity", "node"}:
            return normalized
    return ""


def _canonical_type(value: Any) -> str:
    node_type = _clean_str(value).replace("-", "_").replace(" ", "_").lower()
    aliases = {
        "formevent": "form_event",
        "recentform": "recent_form",
    }
    return aliases.get(node_type, node_type)


def _is_player_node(node: dict[str, Any]) -> bool:
    node_type = _node_type(node)
    if "player" in node_type:
        return True
    labels = [_canonical_type(label) for label in node.get("labels", [])]
    return any("player" in label for label in labels)


def _edge_type(edge: dict[str, Any]) -> str:
    attrs = edge.get("attributes") if isinstance(edge.get("attributes"), dict) else {}
    return _canonical_edge_type(
        edge.get("name")
        or edge.get("type")
        or edge.get("edge_type")
        or attrs.get("type")
        or attrs.get("edge_type")
    )


def _canonical_edge_type(value: Any) -> str:
    edge_type = _canonical_type(value)
    if edge_type in {"news", "has_news", "hasnews"}:
        return "has_news"
    if edge_type in {"form", "formevent", "form_event"}:
        return "form_event"
    if edge_type in {"recentform", "recent_form"}:
        return "recent_form"
    if edge_type in {"playsfor", "plays_for"}:
        return "plays_for"
    return edge_type


def _edge_type_allowed(edge_type: str, allowed_types: tuple[str, ...]) -> bool:
    canonical_allowed = {_canonical_edge_type(value) for value in allowed_types}
    return _canonical_edge_type(edge_type) in canonical_allowed


def _edge_connects_node(edge: dict[str, Any], node_uuid: str) -> bool:
    return node_uuid in {
        _clean_str(edge.get("source_node_uuid")),
        _clean_str(edge.get("target_node_uuid")),
    }


def _edge_other_node_uuid(edge: dict[str, Any], node_uuid: str) -> str:
    source_uuid = _clean_str(edge.get("source_node_uuid"))
    target_uuid = _clean_str(edge.get("target_node_uuid"))
    if source_uuid == node_uuid:
        return target_uuid
    if target_uuid == node_uuid:
        return source_uuid
    return ""


def _same_name(left: str, right: str) -> bool:
    return _normalize_name(left) == _normalize_name(right)


def _similarity(left: str, right: str) -> float:
    left_norm = _normalize_name(left)
    right_norm = _normalize_name(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 100.0
    if _rapidfuzz_fuzz is not None:
        return float(_rapidfuzz_fuzz.ratio(left_norm, right_norm))
    return SequenceMatcher(None, left_norm, right_norm).ratio() * 100.0


def _normalize_name(value: Any) -> str:
    return " ".join(_clean_str(value).casefold().split())


def _normalize_iso3(value: Any) -> str:
    return _clean_str(value).upper()


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _player_names(player: Any) -> list[str]:
    names = [
        getattr(player, "full_name_en", None),
        getattr(player, "full_name", None),
    ]
    aliases = getattr(player, "full_name_alt", None) or []
    if isinstance(aliases, str):
        aliases = [aliases]
    names.extend(aliases)

    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        normalized = _normalize_name(name)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(_clean_str(name))
    return deduped


def _player_id(player: Any) -> str:
    return _clean_str(getattr(player, "id", ""))


def _player_overall_sort_key(player: Any) -> tuple[float, float]:
    derived = getattr(player, "derived", None) or {}
    overall = derived.get("overall") if isinstance(derived, dict) else None
    minutes = getattr(player, "expected_minutes_share", 0) or 0
    try:
        overall_value = float(overall or 0)
    except (TypeError, ValueError):
        overall_value = 0.0
    try:
        minutes_value = float(minutes)
    except (TypeError, ValueError):
        minutes_value = 0.0
    return (overall_value, minutes_value)


def _return_date(node: dict[str, Any]) -> str | None:
    attrs = _node_attributes(node)
    value = (
        attrs.get("return_date")
        or attrs.get("expected_return")
        or attrs.get("expected_return_date")
        or node.get("return_date")
    )
    return _clean_str(value) or None


def _evidence_ref(node: dict[str, Any]) -> dict[str, str]:
    return {
        "id": _node_id(node),
        "type": _node_type(node),
        "summary": _node_summary(node)[:80],
    }


def _fact_ref(node: dict[str, Any], *, player_id: str) -> dict[str, Any]:
    attrs = _node_attributes(node)
    fact = {
        "id": _node_id(node),
        "type": _node_type(node),
        "summary": _node_summary(node),
        "player_id": player_id,
    }
    for key in ("date", "opponent", "result", "sentiment"):
        if attrs.get(key) is not None:
            fact[key] = attrs[key]
    return fact


def _append_warning_once(facts: GraphFacts, warning: str) -> None:
    if warning not in facts.warnings:
        facts.warnings.append(warning)
