from types import SimpleNamespace
from unittest.mock import Mock

from app.services.graph_evidence_query import GraphEvidenceQuery, GraphFacts, PlayerAvailability


def _player(
    player_id: str,
    *,
    team_iso3: str = "BRA",
    external_id: str | None = None,
    name: str | None = None,
    overall: float = 70.0,
):
    return SimpleNamespace(
        id=player_id,
        team_iso3=team_iso3,
        player_external_id=external_id,
        full_name=name or player_id,
        full_name_en=name or player_id,
        full_name_alt=[],
        derived={"overall": overall},
        expected_minutes_share=0.8,
    )


class FakeGraphClient:
    def __init__(self, *, nodes=None, edges=None):
        self.nodes = nodes or []
        self.edges = edges or []

    def get_all_nodes(self, graph_id):
        return self.nodes

    def get_all_edges(self, graph_id):
        return self.edges


class LimitGraphClient(FakeGraphClient):
    def __init__(self, *, nodes=None):
        super().__init__(nodes=nodes, edges=[])
        self.neighbor_limits = []

    def fetch_neighbors(self, node, edge_types, limit):
        self.neighbor_limits.append(limit)
        return [
            {
                "uuid": f"news-{node['uuid']}-{idx}",
                "labels": ["News"],
                "summary": "minor training doubt",
                "attributes": {"sentiment": "doubt"},
            }
            for idx in range(limit)
        ]


def test_graph_evidence_query_with_no_graph(monkeypatch):
    """图谱不可用时全员 available + warning。"""
    monkeypatch.setattr(
        GraphEvidenceQuery,
        "_load_squad",
        lambda self, dataset_id, team_iso3: [_player(f"{team_iso3}-1", team_iso3=team_iso3)],
    )

    query = GraphEvidenceQuery(graphiti_client=Mock(side_effect=ConnectionError))
    facts = query.for_match(
        home_iso3="BRA",
        away_iso3="ARG",
        graph_id="g_1",
        dataset_id="wc2026_fifa_v1",
    )

    assert "graph_unreachable" in facts.warnings
    assert {availability.status for availability in facts.player_availability.values()} == {"available"}


def test_graph_evidence_player_id_alignment_external_id_first(monkeypatch):
    """external_id 精确匹配优先于 name fuzzy。"""
    monkeypatch.setattr(
        GraphEvidenceQuery,
        "_load_squad",
        lambda self, dataset_id, team_iso3: [
            _player("ply_10", team_iso3=team_iso3, external_id="ext-10", name="Neymar")
        ]
        if team_iso3 == "BRA"
        else [],
    )
    client = FakeGraphClient(
        nodes=[
            {
                "uuid": "node-name-match",
                "name": "Neymar",
                "labels": ["Player"],
                "attributes": {"team_iso3": "BRA"},
            },
            {
                "uuid": "node-external-match",
                "name": "Unrelated Alias",
                "labels": ["Player"],
                "attributes": {"metadata": {"external_id": "ext-10"}, "team_iso3": "BRA"},
            },
            {
                "uuid": "injury-from-name",
                "name": "ankle injury",
                "labels": ["Injury"],
                "summary": "Name-match node has an injury.",
                "attributes": {},
            },
            {
                "uuid": "news-from-external",
                "name": "training doubt",
                "labels": ["News"],
                "summary": "External-id node reports a minor doubt.",
                "attributes": {"sentiment": "doubt"},
            },
        ],
        edges=[
            {
                "uuid": "edge-name",
                "name": "injury",
                "source_node_uuid": "node-name-match",
                "target_node_uuid": "injury-from-name",
            },
            {
                "uuid": "edge-external",
                "name": "has_news",
                "source_node_uuid": "node-external-match",
                "target_node_uuid": "news-from-external",
            },
        ],
    )

    facts = GraphEvidenceQuery(graphiti_client=client).for_match(
        home_iso3="BRA",
        away_iso3="ARG",
        graph_id="g_1",
        dataset_id="wc2026_fifa_v1",
    )

    availability = facts.player_availability["ply_10"]
    assert availability.status == "doubtful"
    assert availability.evidence_refs[0]["id"] == "news-from-external"


def test_graph_evidence_query_respects_limits(monkeypatch):
    """MAX_PLAYERS_PER_TEAM = 30, MAX_TOTAL_NODES = 200。"""
    players_by_team = {
        "BRA": [_player(f"BRA-{idx}", team_iso3="BRA", name=f"Brazil {idx}") for idx in range(35)],
        "ARG": [_player(f"ARG-{idx}", team_iso3="ARG", name=f"Argentina {idx}") for idx in range(35)],
    }
    monkeypatch.setattr(
        GraphEvidenceQuery,
        "_load_squad",
        lambda self, dataset_id, team_iso3: players_by_team.get(team_iso3, []),
    )
    nodes = [
        {
            "uuid": player.id,
            "name": player.full_name_en,
            "labels": ["Player"],
            "attributes": {"team_iso3": player.team_iso3},
        }
        for players in players_by_team.values()
        for player in players
    ]
    client = LimitGraphClient(nodes=nodes)

    facts = GraphEvidenceQuery(graphiti_client=client).for_match(
        home_iso3="BRA",
        away_iso3="ARG",
        graph_id="g_1",
        dataset_id="wc2026_fifa_v1",
    )

    assert len(facts.player_availability) == 60
    assert max(client.neighbor_limits) <= GraphEvidenceQuery.MAX_NEIGHBORS_PER_NODE
    assert sum(client.neighbor_limits) <= GraphEvidenceQuery.MAX_TOTAL_NODES


def test_graph_evidence_injury_node_marks_injured(monkeypatch):
    """图谱有 injury 节点的球员，availability.status = injured。"""
    monkeypatch.setattr(
        GraphEvidenceQuery,
        "_load_squad",
        lambda self, dataset_id, team_iso3: [
            _player("ply_1", team_iso3=team_iso3, external_id="ext-1", name="Richarlison")
        ]
        if team_iso3 == "BRA"
        else [],
    )
    client = FakeGraphClient(
        nodes=[
            {
                "uuid": "player-node",
                "name": "Richarlison",
                "labels": ["Player"],
                "attributes": {"external_id": "ext-1", "team_iso3": "BRA"},
            },
            {
                "uuid": "injury-node",
                "name": "hamstring",
                "labels": ["Injury"],
                "summary": "Hamstring injury expected to keep him out for two weeks.",
                "attributes": {"return_date": "2026-06-25"},
            },
        ],
        edges=[
            {
                "uuid": "edge-injury",
                "name": "injury",
                "source_node_uuid": "player-node",
                "target_node_uuid": "injury-node",
            }
        ],
    )

    facts = GraphEvidenceQuery(graphiti_client=client).for_match(
        home_iso3="BRA",
        away_iso3="ARG",
        graph_id="g_1",
        dataset_id="wc2026_fifa_v1",
    )

    availability = facts.player_availability["ply_1"]
    assert availability.status == "injured"
    assert availability.return_date == "2026-06-25"
    assert availability.evidence_refs == [
        {
            "id": "injury-node",
            "type": "injury",
            "summary": "Hamstring injury expected to keep him out for two weeks.",
        }
    ]


def test_graph_facts_aggregate_methods():
    facts = GraphFacts(
        player_availability={"ply_1": PlayerAvailability(status="injured")},
        team_news={"BRA": [{"id": "n1", "summary": "..."}]},
        team_recent_form={},
    )

    assert facts.has_facts_for_team("BRA")
    assert not facts.has_facts_for_team("ARG")
