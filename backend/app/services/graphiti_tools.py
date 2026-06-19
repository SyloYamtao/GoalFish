"""
Graphiti 检索工具服务。

图谱访问全部走 Graphiti；高层报告工具逻辑通过中立 mixin 复用，
不依赖任何云端图谱服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from graphiti_core.edges import EntityEdge
from graphiti_core.errors import GroupsEdgesNotFoundError, NodeNotFoundError
from graphiti_core.nodes import EntityNode as GraphitiEntityNode
from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF, NODE_HYBRID_SEARCH_RRF

from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .graphiti_client import execute_graphiti, run_async
from .graph_models import (
    EdgeInfo,
    NodeInfo,
    PanoramaResult,
    SearchResult,
)
from .graph_tools_common import GraphToolsCommonMixin

logger = get_logger("goalfish.graphiti_tools")


def _dt(value: Any) -> Optional[str]:
    return str(value) if value else None


class GraphitiToolsService(GraphToolsCommonMixin):
    """Graphiti 版本的 Report Agent 图谱工具。"""

    MAX_RETRIES = 3
    RETRY_DELAY = 2.0

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self._llm_client = llm_client
        logger.info("GraphitiToolsService 初始化完成")

    @property
    def llm(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    def _node_to_info(self, node: GraphitiEntityNode) -> NodeInfo:
        return NodeInfo(
            uuid=node.uuid,
            name=node.name or "",
            labels=node.labels or [],
            summary=node.summary or "",
            attributes=node.attributes or {},
        )

    def _edge_to_info(self, edge: EntityEdge, node_map: Optional[Dict[str, NodeInfo]] = None) -> EdgeInfo:
        node_map = node_map or {}
        edge_info = EdgeInfo(
            uuid=edge.uuid,
            name=edge.name or "",
            fact=edge.fact or "",
            source_node_uuid=edge.source_node_uuid or "",
            target_node_uuid=edge.target_node_uuid or "",
            source_node_name=node_map.get(edge.source_node_uuid or "", NodeInfo("", "", [], "", {})).name,
            target_node_name=node_map.get(edge.target_node_uuid or "", NodeInfo("", "", [], "", {})).name,
        )
        edge_info.created_at = _dt(edge.created_at)
        edge_info.valid_at = _dt(edge.valid_at)
        edge_info.invalid_at = _dt(edge.invalid_at)
        edge_info.expired_at = _dt(edge.expired_at)
        return edge_info

    def search_graph(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> SearchResult:
        logger.info(f"Graphiti 搜索: graph_id={graph_id}, scope={scope}, query={query[:50]}")

        async def _search(graphiti):
            if scope == "nodes":
                config = NODE_HYBRID_SEARCH_RRF.model_copy(update={"limit": limit})
                return await graphiti._search(query=query, config=config, group_ids=[graph_id])
            config = EDGE_HYBRID_SEARCH_RRF.model_copy(update={"limit": limit})
            return await graphiti._search(query=query, config=config, group_ids=[graph_id])

        try:
            result = run_async(execute_graphiti(_search))
        except Exception as e:
            logger.warning(f"Graphiti 搜索失败，降级为本地关键词匹配: {e}")
            return self._local_search(graph_id, query, limit, scope)

        facts: List[str] = []
        edges: List[Dict[str, Any]] = []
        nodes: List[Dict[str, Any]] = []

        if scope == "nodes":
            for node in result.nodes:
                info = self._node_to_info(node)
                nodes.append(info.to_dict())
                if info.summary:
                    facts.append(f"[{info.name}]: {info.summary}")
        else:
            node_infos = {node.uuid: self._node_to_info(node) for node in result.nodes}
            for edge in result.edges:
                info = self._edge_to_info(edge, node_infos)
                edges.append(info.to_dict())
                if info.fact:
                    facts.append(info.fact)

        return SearchResult(
            facts=facts,
            edges=edges,
            nodes=nodes,
            query=query,
            total_count=len(facts),
        )

    def _local_search(self, graph_id: str, query: str, limit: int, scope: str) -> SearchResult:
        query_lower = query.lower()
        keywords = [w for w in query_lower.replace(",", " ").replace("，", " ").split() if len(w) > 1]
        facts: List[str] = []
        edges_result: List[Dict[str, Any]] = []
        nodes_result: List[Dict[str, Any]] = []

        if scope == "nodes":
            for node in self.get_all_nodes(graph_id):
                haystack = f"{node.name} {node.summary} {' '.join(node.labels)}".lower()
                if query_lower in haystack or any(keyword in haystack for keyword in keywords):
                    nodes_result.append(node.to_dict())
                    if node.summary:
                        facts.append(f"[{node.name}]: {node.summary}")
                    if len(nodes_result) >= limit:
                        break
        else:
            for edge in self.get_all_edges(graph_id):
                haystack = f"{edge.name} {edge.fact}".lower()
                if query_lower in haystack or any(keyword in haystack for keyword in keywords):
                    edges_result.append(edge.to_dict())
                    if edge.fact:
                        facts.append(edge.fact)
                    if len(edges_result) >= limit:
                        break

        return SearchResult(
            facts=facts,
            edges=edges_result,
            nodes=nodes_result,
            query=query,
            total_count=len(facts),
        )

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        async def _get(graphiti):
            return await GraphitiEntityNode.get_by_group_ids(graphiti.driver, [graph_id])

        nodes = run_async(execute_graphiti(_get))
        return [self._node_to_info(node) for node in nodes]

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        async def _get(graphiti):
            try:
                return await EntityEdge.get_by_group_ids(graphiti.driver, [graph_id])
            except GroupsEdgesNotFoundError:
                return []

        edges = run_async(execute_graphiti(_get))
        node_map = {node.uuid: node for node in self.get_all_nodes(graph_id)}
        return [self._edge_to_info(edge, node_map if include_temporal else {}) for edge in edges]

    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        async def _get(graphiti):
            return await GraphitiEntityNode.get_by_uuid(graphiti.driver, node_uuid)

        try:
            node = run_async(execute_graphiti(_get))
            return self._node_to_info(node)
        except NodeNotFoundError:
            return None

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        return [
            edge for edge in self.get_all_edges(graph_id)
            if edge.source_node_uuid == node_uuid or edge.target_node_uuid == node_uuid
        ]

    def get_entities_by_type(self, graph_id: str, entity_type: str) -> List[NodeInfo]:
        return [node for node in self.get_all_nodes(graph_id) if entity_type in node.labels]

    def get_entity_summary(self, graph_id: str, entity_name: str) -> Dict[str, Any]:
        search_result = self.search_graph(graph_id=graph_id, query=entity_name, limit=20)
        entity_node = next(
            (node for node in self.get_all_nodes(graph_id) if node.name.lower() == entity_name.lower()),
            None,
        )
        related_edges = self.get_node_edges(graph_id, entity_node.uuid) if entity_node else []
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [edge.to_dict() for edge in related_edges],
            "total_relations": len(related_edges),
        }

    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        entity_types: Dict[str, int] = {}
        relation_types: Dict[str, int] = {}

        for node in nodes:
            for label in node.labels:
                if label not in ["Entity", "Node"]:
                    entity_types[label] = entity_types.get(label, 0) + 1
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1

        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types,
        }

    def get_simulation_context(
        self,
        graph_id: str,
        simulation_requirement: str,
        limit: int = 30,
    ) -> Dict[str, Any]:
        search_result = self.search_graph(graph_id=graph_id, query=simulation_requirement, limit=limit)
        stats = self.get_graph_statistics(graph_id)
        entities = []
        for node in self.get_all_nodes(graph_id):
            custom_labels = [label for label in node.labels if label not in ["Entity", "Node"]]
            if custom_labels:
                entities.append({"name": node.name, "type": custom_labels[0], "summary": node.summary})

        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],
            "total_entities": len(entities),
        }

    def quick_search(self, graph_id: str, query: str, limit: int = 10) -> SearchResult:
        return self.search_graph(graph_id=graph_id, query=query, limit=limit, scope="edges")

    def panorama_search(
        self,
        graph_id: str,
        query: str,
        include_expired: bool = True,
        limit: int = 50,
    ) -> PanoramaResult:
        result = PanoramaResult(query=query)
        all_nodes = self.get_all_nodes(graph_id)
        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_nodes = all_nodes
        result.all_edges = all_edges
        result.total_nodes = len(all_nodes)
        result.total_edges = len(all_edges)

        active_facts = []
        historical_facts = []
        for edge in all_edges:
            if not edge.fact:
                continue
            if edge.is_expired or edge.is_invalid:
                valid_at = edge.valid_at or "未知"
                invalid_at = edge.invalid_at or edge.expired_at or "未知"
                historical_facts.append(f"[{valid_at} - {invalid_at}] {edge.fact}")
            else:
                active_facts.append(edge.fact)

        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(",", " ").replace("，", " ").split() if len(w.strip()) > 1]

        def relevance_score(fact: str) -> int:
            fact_lower = fact.lower()
            score = 100 if query_lower in fact_lower else 0
            score += sum(10 for keyword in keywords if keyword in fact_lower)
            return score

        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        return result
