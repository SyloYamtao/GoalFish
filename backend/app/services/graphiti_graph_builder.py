"""
Graphiti 图谱构建服务。

这是本地 Graphiti 图谱构建实现。
"""

from __future__ import annotations

import uuid
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from graphiti_core.edges import EntityEdge
from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError
from graphiti_core.nodes import EntityNode as GraphitiEntityNode
from graphiti_core.nodes import EpisodeType

from ..config import Config
from ..models.task import TaskManager
from ..utils.logger import get_logger
from ..utils.locale import t
from .graphiti_client import execute_graphiti, run_async
from .graphiti_metadata import delete_graph_metadata, load_graph_metadata, save_graph_metadata
from .graphiti_ontology import build_graphiti_edge_type_map, build_graphiti_entity_types

logger = get_logger("goalfish.graphiti_builder")


@dataclass(frozen=True)
class _RosterEntry:
    player_name: str
    team_name: str
    club_name: Optional[str] = None
    jersey_number: Optional[str] = None
    position: Optional[str] = None
    age: Optional[str] = None
    caps: Optional[str] = None


_ROSTER_LINE_RE = re.compile(
    r"^\s*[-*]\s+(?:(?P<number>\d+)\s*号[，,]\s*)?"
    r"(?P<name>[^（(\n]+?)\s*[（(](?P<details>.*?)[）)]\s*$"
)


def _normalize_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text, flags=re.UNICODE)


def _node_attr(node: Any, name: str) -> Any:
    attrs = node.get("attributes", {}) if isinstance(node, dict) else getattr(node, "attributes", {})
    return (attrs or {}).get(name)


def _node_uuid(node: Any) -> str:
    value = node.get("uuid") if isinstance(node, dict) else getattr(node, "uuid", "")
    return str(value or "")


def _node_name(node: Any) -> str:
    value = node.get("name") if isinstance(node, dict) else getattr(node, "name", "")
    return str(value or "")


def _node_labels(node: Any) -> set[str]:
    labels = node.get("labels", []) if isinstance(node, dict) else getattr(node, "labels", [])
    attrs = node.get("attributes", {}) if isinstance(node, dict) else getattr(node, "attributes", {})
    attr_labels = (attrs or {}).get("labels", [])
    result = {str(label) for label in (labels or [])}
    if isinstance(attr_labels, list):
        result.update(str(label) for label in attr_labels)
    return result


def _team_aliases(value: Any) -> list[str]:
    text = str(value or "")
    lowered = text.casefold()
    if "墨西哥" in text or "mexico" in lowered:
        return ["墨西哥", "Mexico", "墨西哥国家男子足球队"]
    if "南非" in text or "south africa" in lowered:
        return ["南非", "South Africa", "南非国家男子足球队"]
    if "韩国" in text or "south korea" in lowered or "korea republic" in lowered or "republic of korea" in lowered:
        return ["韩国", "South Korea", "Korea Republic", "Republic of Korea", "韩国国家男子足球队"]
    if "捷克" in text or "czech" in lowered:
        return ["捷克", "Czechia", "Czech Republic", "捷克国家男子足球队"]
    return []


def _node_aliases(node: Any) -> list[str]:
    aliases: list[str] = []
    for value in (
        _node_name(node),
        _node_attr(node, "全名"),
        _node_attr(node, "球队名称"),
        _node_attr(node, "俱乐部名称"),
    ):
        if value:
            aliases.append(str(value))
            aliases.extend(_team_aliases(value))
    return aliases


def _index_by_alias(nodes: list[Any], labels: str | list[str] | set[str]) -> dict[str, Any]:
    required_labels = {labels} if isinstance(labels, str) else {str(label) for label in labels}
    index: dict[str, Any] = {}
    for node in nodes:
        if not (_node_labels(node) & required_labels):
            continue
        for alias in _node_aliases(node):
            key = _normalize_key(alias)
            if key and key not in index:
                index[key] = node
    return index


def _parse_roster_details(details: str) -> dict[str, Optional[str]]:
    parsed: dict[str, Optional[str]] = {
        "club_name": None,
        "position": None,
        "age": None,
        "caps": None,
    }
    for part in [part.strip() for part in re.split(r"[；;]", details or "") if part.strip()]:
        if part in {"GK", "DF", "MF", "FW"}:
            parsed["position"] = part
        elif part.endswith("岁"):
            parsed["age"] = part.removesuffix("岁")
        elif part.startswith("国家队"):
            parsed["caps"] = part.removeprefix("国家队").strip()
        elif part.startswith("俱乐部"):
            pieces = re.split(r"[：:]", part, maxsplit=1)
            if len(pieces) == 2:
                parsed["club_name"] = pieces[1].strip()
    return parsed


def _team_from_heading(line: str) -> Optional[str]:
    if not line.startswith("#"):
        return None
    if "墨西哥" in line or re.search(r"\bMexico\b", line, flags=re.IGNORECASE):
        return "墨西哥"
    if "南非" in line or re.search(r"\bSouth Africa\b", line, flags=re.IGNORECASE):
        return "South Africa"
    if (
        "韩国" in line
        or re.search(r"\bSouth Korea\b", line, flags=re.IGNORECASE)
        or re.search(r"\bKorea Republic\b", line, flags=re.IGNORECASE)
        or re.search(r"\bRepublic of Korea\b", line, flags=re.IGNORECASE)
    ):
        return "韩国"
    if (
        "捷克" in line
        or re.search(r"\bCzechia\b", line, flags=re.IGNORECASE)
        or re.search(r"\bCzech Republic\b", line, flags=re.IGNORECASE)
    ):
        return "捷克"
    return None


def _split_player_names(value: str) -> list[str]:
    names: list[str] = []
    for raw_name in re.split(r"\s*(?:、|，|,|/|／)\s*", value or ""):
        name = raw_name.strip()
        name = re.sub(r"[。.;；\s]+$", "", name)
        name = re.sub(r"^[\s\-*]+", "", name)
        if name:
            names.append(name)
    return names


def _parse_markdown_table_row(line: str) -> Optional[list[str]]:
    if not line.startswith("|") or not line.endswith("|"):
        return None
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    if not cells or all(re.fullmatch(r":?-{2,}:?", cell or "") for cell in cells):
        return None
    return cells


def _is_roster_table_key(value: str) -> bool:
    return bool(re.search(r"(?:\d+\s*人名单|大名单|球员名单)", value or ""))


def _add_roster_entry(
    entries: dict[tuple[str, str, str], _RosterEntry],
    entry: _RosterEntry,
) -> None:
    if not entry.player_name:
        return
    key = (
        _normalize_key(entry.player_name),
        _normalize_key(entry.team_name),
        _normalize_key(entry.club_name),
    )
    entries.setdefault(key, entry)


def _extract_roster_entries(chunks: list[str]) -> list[_RosterEntry]:
    entries: dict[tuple[str, str, str], _RosterEntry] = {}
    current_team: Optional[str] = None
    in_lineup_section = False

    for raw_line in "\n".join(chunks).splitlines():
        line = raw_line.strip()
        heading_team = _team_from_heading(line)
        if line.startswith("#"):
            in_lineup_section = bool(heading_team and re.search(r"(预计首发|首发|阵容)", line))
        if heading_team:
            current_team = heading_team
            continue

        table_cells = _parse_markdown_table_row(line)
        if table_cells and len(table_cells) >= 2 and current_team and _is_roster_table_key(table_cells[0]):
            for player_name in _split_player_names(table_cells[1]):
                _add_roster_entry(
                    entries,
                    _RosterEntry(player_name=player_name, team_name=current_team),
                )
            continue

        if in_lineup_section and current_team:
            lineup_match = re.match(r"^\s*[-*]\s*(?P<position>[A-Z]{1,3}(?:/[A-Z]{1,3})*)[：:]\s*(?P<names>.+?)\s*$", line)
            if lineup_match:
                for player_name in _split_player_names(lineup_match.group("names")):
                    _add_roster_entry(
                        entries,
                        _RosterEntry(
                            player_name=player_name,
                            team_name=current_team,
                            position=lineup_match.group("position"),
                        ),
                    )
                continue

        match = _ROSTER_LINE_RE.match(line)
        if not match:
            continue

        details = _parse_roster_details(match.group("details"))
        club_name = details.get("club_name")
        player_name = match.group("name").strip()
        if not player_name:
            continue

        entry = _RosterEntry(
            player_name=player_name,
            team_name=current_team or "",
            club_name=club_name,
            jersey_number=match.group("number"),
            position=details.get("position"),
            age=details.get("age"),
            caps=details.get("caps"),
        )
        _add_roster_entry(entries, entry)

    return list(entries.values())


def _canonical_team_name(team_name: str) -> str:
    if "南非" in team_name or "south africa" in team_name.casefold():
        return "South Africa"
    if "墨西哥" in team_name or "mexico" in team_name.casefold():
        return "墨西哥"
    if "韩国" in team_name or "south korea" in team_name.casefold() or "korea republic" in team_name.casefold():
        return "韩国"
    if "捷克" in team_name or "czech" in team_name.casefold():
        return "捷克"
    return team_name


def _team_display_name(team_name: str) -> str:
    if "south africa" in team_name.casefold():
        return "南非"
    if "south korea" in team_name.casefold() or "korea republic" in team_name.casefold():
        return "韩国"
    if "czech" in team_name.casefold():
        return "捷克"
    return team_name


def _team_official_name(team_name: str) -> str:
    canonical = _canonical_team_name(team_name)
    if canonical == "墨西哥":
        return "墨西哥国家男子足球队"
    if canonical == "South Africa":
        return "南非国家男子足球队"
    if canonical == "韩国":
        return "韩国国家男子足球队"
    if canonical == "捷克":
        return "捷克国家男子足球队"
    return canonical


def _should_update_player_name(node: Any, canonical_name: str) -> bool:
    current_name = _node_name(node).strip()
    if not current_name:
        return True
    current_key = _normalize_key(current_name)
    canonical_key = _normalize_key(canonical_name)
    if current_key == canonical_key:
        return False
    return bool(current_key and current_key in canonical_key and len(current_key) < len(canonical_key) * 0.7)


def _dt(value: Any) -> Optional[str]:
    return str(value) if value else None


def _node_to_dict(node: GraphitiEntityNode) -> Dict[str, Any]:
    return {
        "uuid": node.uuid,
        "name": node.name or "",
        "labels": node.labels or [],
        "summary": node.summary or "",
        "attributes": node.attributes or {},
        "created_at": _dt(node.created_at),
    }


def _edge_to_dict(edge: EntityEdge, node_map: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    node_map = node_map or {}
    return {
        "uuid": edge.uuid,
        "name": edge.name or "",
        "fact": edge.fact or "",
        "fact_type": edge.name or "",
        "source_node_uuid": edge.source_node_uuid or "",
        "target_node_uuid": edge.target_node_uuid or "",
        "source_node_name": node_map.get(edge.source_node_uuid or "", ""),
        "target_node_name": node_map.get(edge.target_node_uuid or "", ""),
        "attributes": {},
        "created_at": _dt(edge.created_at),
        "valid_at": _dt(edge.valid_at),
        "invalid_at": _dt(edge.invalid_at),
        "expired_at": _dt(edge.expired_at),
        "episodes": [str(e) for e in (edge.episodes or [])],
    }


class GraphitiGraphBuilderService:
    """使用本地 Graphiti 构建和读取图谱。"""

    def __init__(self):
        self.task_manager = TaskManager()

    def create_graph(self, name: str) -> str:
        graph_id = f"goalfish_{uuid.uuid4().hex[:16]}"
        save_graph_metadata(graph_id, {"name": name, "backend": "graphiti"})
        logger.info(f"Graphiti graph metadata created: graph_id={graph_id}, name={name}")
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        edge_type_map = build_graphiti_edge_type_map(ontology)
        serializable_edge_type_map = {
            f"{source}->{target}": names
            for (source, target), names in edge_type_map.items()
        }
        save_graph_metadata(graph_id, {
            "ontology": ontology,
            "edge_type_map": serializable_edge_type_map,
        })
        logger.info(
            "Graphiti ontology saved: "
            f"graph_id={graph_id}, entity_types={len(ontology.get('entity_types', []))}, "
            f"edge_types={len(ontology.get('edge_types', []))}, edge_type_pairs={len(edge_type_map)}"
        )

    def _get_entity_types(self, graph_id: str):
        metadata = load_graph_metadata(graph_id)
        ontology = metadata.get("ontology") or {}
        entity_types = build_graphiti_entity_types(ontology) if ontology else None
        logger.debug(
            "Graphiti entity type load: "
            f"graph_id={graph_id}, entity_type_count={len(entity_types or {})}"
        )
        return entity_types

    def _get_existing_episode_uuids_by_name(self, graph_id: str, episode_names: list[str]) -> dict[str, str]:
        if not episode_names:
            return {}

        async def _get(graphiti):
            driver = getattr(graphiti, "driver", None)
            if driver is None:
                return {}
            records, _, _ = await driver.execute_query(
                """
                MATCH (e:Episodic {group_id: $group_id})
                WHERE e.name IN $episode_names
                RETURN e.name AS name, e.uuid AS uuid
                """,
                group_id=graph_id,
                episode_names=episode_names,
                routing_="r",
            )
            return {
                str(record["name"]): str(record["uuid"])
                for record in records
                if record.get("name") and record.get("uuid")
            }

        return run_async(execute_graphiti(_get))

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        episode_uuids: List[str] = []
        total_chunks = len(chunks)
        if total_chunks == 0:
            return episode_uuids

        entity_types = self._get_entity_types(graph_id)
        logger.info(
            "Graphiti text batch ingest start: "
            f"graph_id={graph_id}, chunks={total_chunks}, batch_size={batch_size}, "
            f"entity_type_count={len(entity_types or {})}"
        )

        async def _ensure_indices(graphiti):
            logger.debug(f"Graphiti build_indices_and_constraints start: graph_id={graph_id}")
            await graphiti.build_indices_and_constraints()
            logger.debug(f"Graphiti build_indices_and_constraints complete: graph_id={graph_id}")

        run_async(execute_graphiti(_ensure_indices))

        episode_names = [f"{graph_id}_chunk_{i}" for i in range(1, total_chunks + 1)]
        existing_episode_uuids_by_name = self._get_existing_episode_uuids_by_name(graph_id, episode_names)
        if existing_episode_uuids_by_name:
            logger.info(
                "Graphiti existing episodes detected: "
                f"graph_id={graph_id}, existing={len(existing_episode_uuids_by_name)}/{total_chunks}"
            )

        for i, chunk in enumerate(chunks, start=1):
            episode_name = f"{graph_id}_chunk_{i}"
            existing_episode_uuid = existing_episode_uuids_by_name.get(episode_name)
            if existing_episode_uuid:
                episode_uuids.append(existing_episode_uuid)
                logger.debug(
                    "Graphiti add episode skipped, already exists: "
                    f"graph_id={graph_id}, chunk={i}/{total_chunks}, "
                    f"name={episode_name}, episode_uuid={existing_episode_uuid}"
                )
                if progress_callback:
                    progress = i / total_chunks
                    batch_num = (i + batch_size - 1) // batch_size
                    total_batches = (total_chunks + batch_size - 1) // batch_size
                    progress_callback(
                        t("progress.sendingBatch", current=batch_num, total=total_batches, chunks=1),
                        progress,
                    )
                continue

            logger.debug(
                "Graphiti add episode start: "
                f"graph_id={graph_id}, chunk={i}/{total_chunks}, name={episode_name}, chars={len(chunk)}"
            )

            async def _add(graphiti):
                return await graphiti.add_episode(
                    name=episode_name,
                    episode_body=chunk,
                    source_description="GoalFish uploaded document chunk",
                    reference_time=datetime.now(),
                    source=EpisodeType.text,
                    group_id=graph_id,
                    entity_types=entity_types,
                )

            result = run_async(execute_graphiti(_add))
            episode_uuid = getattr(getattr(result, "episode", None), "uuid", None)
            if not episode_uuid:
                raise ValueError(f"Graphiti add_episode 未返回 episode uuid: graph_id={graph_id}, chunk={i}")
            episode_uuids.append(episode_uuid)
            logger.debug(
                "Graphiti add episode complete: "
                f"graph_id={graph_id}, chunk={i}/{total_chunks}, episode_uuid={episode_uuid}"
            )

            if progress_callback:
                progress = i / total_chunks
                batch_num = (i + batch_size - 1) // batch_size
                total_batches = (total_chunks + batch_size - 1) // batch_size
                progress_callback(
                    t("progress.sendingBatch", current=batch_num, total=total_batches, chunks=1),
                    progress,
                )

        logger.info(
            "Graphiti text batch ingest complete: "
            f"graph_id={graph_id}, episodes={len(episode_uuids)}"
        )
        try:
            self._backfill_deterministic_edges(graph_id, chunks, episode_uuids)
        except Exception:
            logger.exception(f"Graphiti deterministic edge backfill failed: graph_id={graph_id}")
        try:
            self._enforce_edge_ontology(graph_id)
        except Exception:
            logger.exception(f"Graphiti edge ontology enforcement failed: graph_id={graph_id}")
        return episode_uuids

    def _edge_ontology_names(self, graph_id: str) -> list[str]:
        ontology = (load_graph_metadata(graph_id).get("ontology") or {})
        edge_types = ontology.get("edge_types", []) or []
        return [str(edge_def.get("name", "")).strip() for edge_def in edge_types if edge_def.get("name")]

    def _supports_plays_for_backfill(self, graph_id: str) -> bool:
        edge_names = self._edge_ontology_names(graph_id)
        if not edge_names:
            return True
        return any(name.upper() == "PLAYS_FOR" for name in edge_names)

    def _entity_ontology_names(self, graph_id: str) -> set[str]:
        ontology = (load_graph_metadata(graph_id).get("ontology") or {})
        entity_types = ontology.get("entity_types", []) or []
        return {str(entity_def.get("name", "")).strip() for entity_def in entity_types if entity_def.get("name")}

    def _enforce_edge_ontology(self, graph_id: str) -> None:
        allowed_edge_names = self._edge_ontology_names(graph_id)
        if not allowed_edge_names:
            logger.debug(f"Graphiti edge ontology enforcement skipped, no ontology: graph_id={graph_id}")
            return

        allowed_upper = {name.upper() for name in allowed_edge_names}
        delete_non_ontology_edges = Config.GRAPHITI_DELETE_NON_ONTOLOGY_EDGES
        renames = []
        if "FACES_OFF_AGAINST" in allowed_upper:
            renames.append({"from": "FACES_IN_MATCH", "to": "FACES_OFF_AGAINST"})

        async def _enforce(graphiti):
            renamed_count = 0
            normalized_count = 0
            deleted_count = 0
            non_ontology_edge_count = 0

            if renames:
                records, _, _ = await graphiti.driver.execute_query(
                    """
                    UNWIND $renames AS row
                    MATCH ()-[r:RELATES_TO {group_id: $group_id}]->()
                    WHERE toUpper(r.name) = row.from
                    SET r.name = row.to
                    RETURN count(r) AS renamed_count
                    """,
                    group_id=graph_id,
                    renames=renames,
                )
                renamed_count = records[0]["renamed_count"] if records else 0

            records, _, _ = await graphiti.driver.execute_query(
                """
                UNWIND $allowed_edge_names AS allowed_name
                MATCH ()-[r:RELATES_TO {group_id: $group_id}]->()
                WHERE toUpper(r.name) = toUpper(allowed_name) AND r.name <> allowed_name
                SET r.name = allowed_name
                RETURN count(r) AS normalized_count
                """,
                group_id=graph_id,
                allowed_edge_names=allowed_edge_names,
            )
            normalized_count = records[0]["normalized_count"] if records else 0

            if delete_non_ontology_edges:
                records, _, _ = await graphiti.driver.execute_query(
                    """
                    MATCH ()-[r:RELATES_TO {group_id: $group_id}]->()
                    WHERE NOT toUpper(r.name) IN $allowed_upper
                    DELETE r
                    RETURN count(r) AS deleted_count
                    """,
                    group_id=graph_id,
                    allowed_upper=list(allowed_upper),
                )
                deleted_count = records[0]["deleted_count"] if records else 0
            else:
                records, _, _ = await graphiti.driver.execute_query(
                    """
                    MATCH ()-[r:RELATES_TO {group_id: $group_id}]->()
                    WHERE NOT toUpper(r.name) IN $allowed_upper
                    RETURN count(r) AS non_ontology_edge_count
                    """,
                    group_id=graph_id,
                    allowed_upper=list(allowed_upper),
                )
                non_ontology_edge_count = records[0]["non_ontology_edge_count"] if records else 0

            return {
                "renamed_count": renamed_count,
                "normalized_count": normalized_count,
                "deleted_count": deleted_count,
                "non_ontology_edge_count": non_ontology_edge_count,
            }

        result = run_async(execute_graphiti(_enforce))
        logger.info(
            "Graphiti edge ontology enforcement complete: "
            f"graph_id={graph_id}, allowed_edges={len(allowed_edge_names)}, "
            f"renamed={result['renamed_count']}, normalized={result['normalized_count']}, "
            f"deleted={result['deleted_count']}, "
            f"preserved_non_ontology={result['non_ontology_edge_count']}, "
            f"delete_non_ontology_edges={delete_non_ontology_edges}"
        )


    def _backfill_deterministic_edges(
        self,
        graph_id: str,
        chunks: List[str],
        episode_uuids: List[str],
    ) -> None:
        if not self._supports_plays_for_backfill(graph_id):
            logger.debug(f"Graphiti PLAYS_FOR backfill skipped by ontology: graph_id={graph_id}")
            return

        roster_entries = _extract_roster_entries(chunks)

        async def _backfill(graphiti):
            try:
                nodes = await GraphitiEntityNode.get_by_group_ids(graphiti.driver, [graph_id])
            except GroupsNodesNotFoundError:
                logger.debug(f"Graphiti PLAYS_FOR backfill skipped, no nodes: graph_id={graph_id}")
                return {"node_count": 0, "edge_count": 0, "player_update_count": 0}

            payload = self._build_plays_for_backfill_payload(
                graph_id=graph_id,
                nodes=nodes,
                roster_entries=roster_entries,
                episode_uuids=episode_uuids,
            )
            created_at = datetime.now(timezone.utc)

            if payload["nodes"]:
                await graphiti.driver.execute_query(
                    """
                    UNWIND $nodes AS row
                    MERGE (n:Entity {uuid: row.uuid})
                    SET n += row.props
                    FOREACH (_ IN CASE WHEN row.type = 'Player' THEN [1] ELSE [] END | SET n:Player)
                    FOREACH (_ IN CASE WHEN row.type = 'FootballPlayer' THEN [1] ELSE [] END | SET n:FootballPlayer)
                    FOREACH (_ IN CASE WHEN row.type = 'FootballTeam' THEN [1] ELSE [] END | SET n:FootballTeam)
                    FOREACH (_ IN CASE WHEN row.type = 'FootballClub' THEN [1] ELSE [] END | SET n:FootballClub)
                    FOREACH (_ IN CASE WHEN row.type = 'NationalTeam' THEN [1] ELSE [] END | SET n:NationalTeam)
                    FOREACH (_ IN CASE WHEN row.type = 'Organization' THEN [1] ELSE [] END | SET n:Organization)
                    RETURN count(n) AS node_count
                    """,
                    nodes=payload["nodes"],
                )

            if payload["player_updates"]:
                await graphiti.driver.execute_query(
                    """
                    UNWIND $player_updates AS row
                    MATCH (n:Entity {uuid: row.uuid, group_id: $group_id})
                    SET n += row.props
                    RETURN count(n) AS player_update_count
                    """,
                    group_id=graph_id,
                    player_updates=payload["player_updates"],
                )

            if payload["edges"]:
                await graphiti.driver.execute_query(
                    """
                    UNWIND $edges AS edge
                    MATCH (source:Entity {uuid: edge.source_uuid, group_id: $group_id})
                    MATCH (target:Entity {uuid: edge.target_uuid, group_id: $group_id})
                    MERGE (source)-[r:RELATES_TO {group_id: $group_id, name: edge.name}]->(target)
                    ON CREATE SET
                        r.uuid = edge.uuid,
                        r.fact = edge.fact,
                        r.episodes = edge.episodes,
                        r.created_at = $created_at,
                        r.expired_at = null,
                        r.valid_at = null,
                        r.invalid_at = null
                    ON MATCH SET
                        r.uuid = coalesce(r.uuid, edge.uuid),
                        r.fact = CASE WHEN r.fact IS NULL OR r.fact = '' THEN edge.fact ELSE r.fact END,
                        r.episodes = coalesce(r.episodes, []) + [
                            episode IN edge.episodes
                            WHERE NOT episode IN coalesce(r.episodes, [])
                        ]
                    RETURN count(r) AS edge_count
                    """,
                    group_id=graph_id,
                    edges=payload["edges"],
                    created_at=created_at,
                )

            return {
                "node_count": len(payload["nodes"]),
                "edge_count": len(payload["edges"]),
                "player_update_count": len(payload["player_updates"]),
            }

        result = run_async(execute_graphiti(_backfill))
        logger.info(
            "Graphiti deterministic PLAYS_FOR backfill complete: "
            f"graph_id={graph_id}, roster_entries={len(roster_entries)}, "
            f"created_nodes={result['node_count']}, player_updates={result['player_update_count']}, "
            f"planned_edges={result['edge_count']}"
        )

    def _build_plays_for_backfill_payload(
        self,
        graph_id: str,
        nodes: List[Any],
        roster_entries: List[_RosterEntry],
        episode_uuids: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        existing_nodes = list(nodes)
        existing_labels = {label for node in existing_nodes for label in _node_labels(node)}
        entity_names = self._entity_ontology_names(graph_id)

        def choose_node_type(candidates: list[str], default: str) -> str:
            for candidate in candidates:
                if candidate in entity_names:
                    return candidate
            for candidate in candidates:
                if candidate in existing_labels:
                    return candidate
            return default

        player_node_type = choose_node_type(["Player", "FootballPlayer"], "FootballPlayer")
        team_node_type = choose_node_type(["FootballTeam", "NationalTeam"], "NationalTeam")
        club_node_type = choose_node_type(["FootballClub", "FootballTeam", "Organization"], "FootballClub")

        player_labels = {"Player", "FootballPlayer"}
        team_labels = {"FootballTeam", "NationalTeam"}
        club_labels = {"FootballClub", club_node_type}
        player_index = _index_by_alias(existing_nodes, player_labels)
        club_index = _index_by_alias(existing_nodes, club_labels)
        team_index = _index_by_alias(existing_nodes, team_labels)

        created_nodes: list[dict[str, Any]] = []
        player_updates_by_uuid: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []
        edge_keys: set[tuple[str, str, str]] = set()

        def add_to_index(index: dict[str, Any], node: dict[str, Any]) -> None:
            for alias in _node_aliases(node):
                key = _normalize_key(alias)
                if key:
                    index.setdefault(key, node)

        def make_node(node_type: str, name: str, attrs: dict[str, Any], summary: str) -> dict[str, Any]:
            node_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"goalfish:{graph_id}:{node_type}:{_normalize_key(name)}"))
            labels = ["Entity", node_type]
            props = {
                "uuid": node_uuid,
                "name": name,
                "group_id": graph_id,
                "summary": summary,
                "created_at": datetime.now(timezone.utc),
                "labels": labels,
                **attrs,
            }
            row = {"uuid": node_uuid, "type": node_type, "props": props}
            created_nodes.append(row)
            return {
                "uuid": node_uuid,
                "name": name,
                "labels": labels,
                "attributes": attrs,
            }

        def ensure_player(entry: _RosterEntry) -> Any:
            key = _normalize_key(entry.player_name)
            node = player_index.get(key)
            props = {
                "全名": entry.player_name,
            }
            if entry.club_name:
                props["所属俱乐部"] = entry.club_name
            if entry.jersey_number:
                props["球衣号码"] = entry.jersey_number
            if entry.position:
                props["场上位置"] = entry.position
            if entry.age:
                props["年龄"] = entry.age
            if entry.caps:
                props["国家队出场数"] = entry.caps

            if node:
                if _should_update_player_name(node, entry.player_name):
                    props["name"] = entry.player_name
                existing_props = player_updates_by_uuid.setdefault(_node_uuid(node), {})
                existing_props.update(props)
                return node

            node = make_node(
                player_node_type,
                entry.player_name,
                props,
                (
                    f"{entry.player_name} 是{_team_display_name(entry.team_name)}国家队球员，效力于{entry.club_name}。"
                    if entry.club_name
                    else f"{entry.player_name} 是{_team_display_name(entry.team_name)}国家队球员。"
                ),
            )
            add_to_index(player_index, node)
            return node

        def ensure_club(club_name: str) -> Any:
            key = _normalize_key(club_name)
            node = club_index.get(key)
            if node:
                return node
            node = make_node(
                club_node_type,
                club_name,
                {"俱乐部名称": club_name, "球队名称": club_name},
                f"{club_name} 是名单中球员所属的足球俱乐部。",
            )
            add_to_index(club_index, node)
            return node

        def ensure_team(team_name: str) -> Optional[Any]:
            if not team_name:
                return None
            for alias in [team_name, *_team_aliases(team_name)]:
                node = team_index.get(_normalize_key(alias))
                if node:
                    return node
            canonical_name = _canonical_team_name(team_name)
            node = make_node(
                team_node_type,
                canonical_name,
                {"全名": _team_official_name(team_name), "球队名称": _team_official_name(team_name)},
                f"{_team_display_name(team_name)}国家男子足球队。",
            )
            add_to_index(team_index, node)
            return node

        def add_edge(source: Any, target: Any, fact: str) -> None:
            source_uuid = _node_uuid(source)
            target_uuid = _node_uuid(target)
            key = (source_uuid, target_uuid, "PLAYS_FOR")
            if not source_uuid or not target_uuid or key in edge_keys:
                return
            edge_keys.add(key)
            edge_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"goalfish:{graph_id}:PLAYS_FOR:{source_uuid}:{target_uuid}"))
            edges.append(
                {
                    "uuid": edge_uuid,
                    "source_uuid": source_uuid,
                    "target_uuid": target_uuid,
                    "name": "PLAYS_FOR",
                    "fact": fact,
                    "episodes": [str(episode_uuid) for episode_uuid in episode_uuids],
                }
            )

        for entry in roster_entries:
            player = ensure_player(entry)
            if entry.club_name:
                club = ensure_club(entry.club_name)
                add_edge(player, club, f"{entry.player_name}效力于{entry.club_name}。")
            team = ensure_team(entry.team_name)
            if team:
                add_edge(
                    player,
                    team,
                    f"{entry.player_name}代表{_team_display_name(entry.team_name)}国家队。",
                )

        for node in existing_nodes:
            if not (_node_labels(node) & player_labels):
                continue
            club_name = _node_attr(node, "所属俱乐部")
            if not club_name:
                continue
            club = ensure_club(str(club_name))
            player_name = str(_node_attr(node, "全名") or _node_name(node))
            add_edge(node, club, f"{player_name}效力于{club_name}。")

        player_updates = [
            {"uuid": player_uuid, "props": props}
            for player_uuid, props in player_updates_by_uuid.items()
            if props
        ]
        return {
            "nodes": created_nodes,
            "player_updates": player_updates,
            "edges": edges,
        }

    def _wait_for_episodes(
        self,
        episode_uuids: List[str],
        progress_callback: Optional[Callable] = None,
        timeout: int = 600,
    ):
        logger.info(
            "Graphiti episode wait skipped: "
            f"graph_id_episodes={len(episode_uuids)}, timeout={timeout}"
        )
        if progress_callback:
            progress_callback(t("progress.processingComplete", completed=len(episode_uuids), total=len(episode_uuids)), 1.0)

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        async def _get(graphiti):
            logger.debug(f"Graphiti get nodes start: graph_id={graph_id}")
            try:
                nodes = await GraphitiEntityNode.get_by_group_ids(graphiti.driver, [graph_id])
            except GroupsNodesNotFoundError:
                logger.debug(f"Graphiti no nodes found for graph_id={graph_id}")
                return [], []

            try:
                logger.debug(f"Graphiti get edges start: graph_id={graph_id}")
                edges = await EntityEdge.get_by_group_ids(graphiti.driver, [graph_id])
            except GroupsEdgesNotFoundError:
                logger.debug(f"Graphiti no edges found for graph_id={graph_id}")
                edges = []
            return nodes, edges

        nodes, edges = run_async(execute_graphiti(_get))
        node_map = {node.uuid: node.name or "" for node in nodes}
        nodes_data = [_node_to_dict(node) for node in nodes]
        edges_data = [_edge_to_dict(edge, node_map) for edge in edges]
        logger.info(
            "Graphiti graph data loaded: "
            f"graph_id={graph_id}, nodes={len(nodes_data)}, edges={len(edges_data)}"
        )

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }

    def delete_graph(self, graph_id: str):
        async def _delete(graphiti):
            logger.info(f"Graphiti delete graph start: graph_id={graph_id}")
            await graphiti.driver.execute_query(
                """
                MATCH (n {group_id: $group_id})
                DETACH DELETE n
                """,
                group_id=graph_id,
            )

        run_async(execute_graphiti(_delete))
        delete_graph_metadata(graph_id)
        logger.info(f"Graphiti delete graph complete: graph_id={graph_id}")
