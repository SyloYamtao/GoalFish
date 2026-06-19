"""
Graphiti 实体读取服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from graphiti_core.edges import EntityEdge
from graphiti_core.errors import EdgeNotFoundError, GroupsEdgesNotFoundError, NodeNotFoundError
from graphiti_core.nodes import EntityNode as GraphitiEntityNode

from ..utils.logger import get_logger
from .graphiti_client import execute_graphiti, run_async
from .graph_models import EntityNode, FilteredEntities

logger = get_logger("goalfish.graphiti_entity_reader")


class GraphitiEntityReader:
    """从 Graphiti/Neo4j 中读取实体并转换为现有数据结构。"""

    def get_all_nodes(self, graph_id: str) -> List[Dict[str, Any]]:
        async def _get(graphiti):
            return await GraphitiEntityNode.get_by_group_ids(graphiti.driver, [graph_id])

        nodes = run_async(execute_graphiti(_get))
        return [
            {
                "uuid": node.uuid,
                "name": node.name or "",
                "labels": node.labels or [],
                "summary": node.summary or "",
                "attributes": node.attributes or {},
            }
            for node in nodes
        ]

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        async def _get(graphiti):
            try:
                return await EntityEdge.get_by_group_ids(graphiti.driver, [graph_id])
            except GroupsEdgesNotFoundError:
                return []

        edges = run_async(execute_graphiti(_get))
        return [
            {
                "uuid": edge.uuid,
                "name": edge.name or "",
                "fact": edge.fact or "",
                "source_node_uuid": edge.source_node_uuid or "",
                "target_node_uuid": edge.target_node_uuid or "",
                "attributes": {},
            }
            for edge in edges
        ]

    def get_node_edges(self, node_uuid: str) -> List[Dict[str, Any]]:
        async def _get(graphiti):
            return await EntityEdge.get_by_node_uuid(graphiti.driver, node_uuid)

        try:
            edges = run_async(execute_graphiti(_get))
        except (EdgeNotFoundError, NodeNotFoundError):
            edges = []
        return [
            {
                "uuid": edge.uuid,
                "name": edge.name or "",
                "fact": edge.fact or "",
                "source_node_uuid": edge.source_node_uuid or "",
                "target_node_uuid": edge.target_node_uuid or "",
                "attributes": {},
            }
            for edge in edges
        ]

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_entity_types: Optional[List[str]] = None,
        enrich_with_edges: bool = True,
    ) -> FilteredEntities:
        all_nodes = self.get_all_nodes(graph_id)
        all_edges = self.get_all_edges(graph_id) if enrich_with_edges else []
        node_map = {n["uuid"]: n for n in all_nodes}
        filtered_entities: List[EntityNode] = []
        entity_types_found: Set[str] = set()

        for node in all_nodes:
            labels = node.get("labels", [])
            custom_labels = [label for label in labels if label not in ["Entity", "Node"]]
            if not custom_labels:
                continue
            if defined_entity_types:
                matching_labels = [label for label in custom_labels if label in defined_entity_types]
                if not matching_labels:
                    continue
                entity_type = matching_labels[0]
            else:
                entity_type = custom_labels[0]

            entity_types_found.add(entity_type)
            entity = EntityNode(
                uuid=node["uuid"],
                name=node["name"],
                labels=labels,
                summary=node.get("summary", ""),
                attributes=node.get("attributes", {}),
            )

            if enrich_with_edges:
                related_edges = []
                related_node_uuids = set()
                for edge in all_edges:
                    if edge["source_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "outgoing",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "target_node_uuid": edge["target_node_uuid"],
                        })
                        related_node_uuids.add(edge["target_node_uuid"])
                    elif edge["target_node_uuid"] == node["uuid"]:
                        related_edges.append({
                            "direction": "incoming",
                            "edge_name": edge["name"],
                            "fact": edge["fact"],
                            "source_node_uuid": edge["source_node_uuid"],
                        })
                        related_node_uuids.add(edge["source_node_uuid"])

                entity.related_edges = related_edges
                entity.related_nodes = [
                    {
                        "uuid": node_map[uuid]["uuid"],
                        "name": node_map[uuid]["name"],
                        "labels": node_map[uuid]["labels"],
                        "summary": node_map[uuid].get("summary", ""),
                    }
                    for uuid in related_node_uuids
                    if uuid in node_map
                ]

            filtered_entities.append(entity)

        return FilteredEntities(
            entities=filtered_entities,
            entity_types=entity_types_found,
            total_count=len(all_nodes),
            filtered_count=len(filtered_entities),
        )

    def get_entity_with_context(self, graph_id: str, entity_uuid: str) -> Optional[EntityNode]:
        async def _get(graphiti):
            return await GraphitiEntityNode.get_by_uuid(graphiti.driver, entity_uuid)

        try:
            node = run_async(execute_graphiti(_get))
        except NodeNotFoundError:
            return None

        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n["uuid"]: n for n in all_nodes}
        edges = self.get_node_edges(entity_uuid)
        related_edges = []
        related_node_uuids = set()

        for edge in edges:
            if edge["source_node_uuid"] == entity_uuid:
                related_edges.append({
                    "direction": "outgoing",
                    "edge_name": edge["name"],
                    "fact": edge["fact"],
                    "target_node_uuid": edge["target_node_uuid"],
                })
                related_node_uuids.add(edge["target_node_uuid"])
            else:
                related_edges.append({
                    "direction": "incoming",
                    "edge_name": edge["name"],
                    "fact": edge["fact"],
                    "source_node_uuid": edge["source_node_uuid"],
                })
                related_node_uuids.add(edge["source_node_uuid"])

        return EntityNode(
            uuid=node.uuid,
            name=node.name or "",
            labels=node.labels or [],
            summary=node.summary or "",
            attributes=node.attributes or {},
            related_edges=related_edges,
            related_nodes=[
                {
                    "uuid": node_map[uuid]["uuid"],
                    "name": node_map[uuid]["name"],
                    "labels": node_map[uuid]["labels"],
                    "summary": node_map[uuid].get("summary", ""),
                }
                for uuid in related_node_uuids
                if uuid in node_map
            ],
        )

    def get_entities_by_type(
        self,
        graph_id: str,
        entity_type: str,
        enrich_with_edges: bool = True,
    ) -> List[EntityNode]:
        return self.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=[entity_type],
            enrich_with_edges=enrich_with_edges,
        ).entities
