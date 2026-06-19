import asyncio
from types import SimpleNamespace

from flask import Flask
from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError

from app.api import graph as graph_api
from app.models.project import Project, ProjectStatus
from app.services import graphiti_graph_builder as builder_module
from app.services.graphiti_graph_builder import GraphitiGraphBuilderService
from app.services.graphiti_property_sanitizer import (
    install_graphiti_neo4j_property_sanitizer,
    sanitize_graphiti_entity_nodes_for_neo4j,
)


def test_graphiti_add_text_batches_does_not_pass_uuid_for_new_episode(monkeypatch):
    captured_kwargs = []

    class FakeGraphiti:
        async def build_indices_and_constraints(self):
            return None

        async def add_episode(self, **kwargs):
            captured_kwargs.append(kwargs)
            return SimpleNamespace(episode=SimpleNamespace(uuid="episode-created-by-graphiti"))

    def fake_execute_graphiti(coro_factory):
        return coro_factory(FakeGraphiti())

    def fake_run_async(awaitable):
        return asyncio.run(awaitable)

    monkeypatch.setattr(builder_module, "execute_graphiti", fake_execute_graphiti)
    monkeypatch.setattr(builder_module, "run_async", fake_run_async)
    monkeypatch.setattr(GraphitiGraphBuilderService, "_get_entity_types", lambda self, graph_id: {})
    monkeypatch.setattr(
        GraphitiGraphBuilderService,
        "_backfill_deterministic_edges",
        lambda self, graph_id, chunks, episode_uuids: None,
    )
    monkeypatch.setattr(
        GraphitiGraphBuilderService,
        "_enforce_edge_ontology",
        lambda self, graph_id: None,
    )

    builder = GraphitiGraphBuilderService()

    episode_uuids = builder.add_text_batches("graph_1", ["hello world"])

    assert episode_uuids == ["episode-created-by-graphiti"]
    assert "uuid" not in captured_kwargs[0]


def test_graphiti_add_text_batches_skips_existing_named_episode(monkeypatch):
    captured_episode_names = []
    progress_updates = []

    class FakeDriver:
        async def execute_query(self, query, **kwargs):
            assert kwargs["group_id"] == "graph_1"
            assert "graph_1_chunk_1" in kwargs["episode_names"]
            return [{"name": "graph_1_chunk_1", "uuid": "episode-existing"}], None, None

    class FakeGraphiti:
        driver = FakeDriver()

        async def build_indices_and_constraints(self):
            return None

        async def add_episode(self, **kwargs):
            captured_episode_names.append(kwargs["name"])
            return SimpleNamespace(episode=SimpleNamespace(uuid="episode-new"))

    def fake_execute_graphiti(coro_factory):
        return coro_factory(FakeGraphiti())

    def fake_run_async(awaitable):
        return asyncio.run(awaitable)

    monkeypatch.setattr(builder_module, "execute_graphiti", fake_execute_graphiti)
    monkeypatch.setattr(builder_module, "run_async", fake_run_async)
    monkeypatch.setattr(GraphitiGraphBuilderService, "_get_entity_types", lambda self, graph_id: {})
    monkeypatch.setattr(
        GraphitiGraphBuilderService,
        "_backfill_deterministic_edges",
        lambda self, graph_id, chunks, episode_uuids: None,
    )
    monkeypatch.setattr(
        GraphitiGraphBuilderService,
        "_enforce_edge_ontology",
        lambda self, graph_id: None,
    )

    episode_uuids = GraphitiGraphBuilderService().add_text_batches(
        "graph_1",
        ["already processed", "new chunk"],
        progress_callback=lambda message, progress: progress_updates.append(progress),
    )

    assert episode_uuids == ["episode-existing", "episode-new"]
    assert captured_episode_names == ["graph_1_chunk_2"]
    assert progress_updates == [0.5, 1.0]


def test_graphiti_backfills_player_team_and_club_edges(monkeypatch):
    nodes = [
        SimpleNamespace(
            uuid="player-ochoa",
            name="choa",
            labels=["Entity", "FootballPlayer"],
            summary="",
            attributes={"全名": "Guillermo Ochoa", "所属俱乐部": "AEL Limassol"},
            created_at=None,
        ),
        SimpleNamespace(
            uuid="team-mexico",
            name="墨西哥",
            labels=["Entity", "NationalTeam"],
            summary="",
            attributes={"球队名称": "墨西哥国家男子足球队"},
            created_at=None,
        ),
        SimpleNamespace(
            uuid="club-ael",
            name="AEL Limassol",
            labels=["Entity", "FootballClub"],
            summary="",
            attributes={"俱乐部名称": "AEL Limassol"},
            created_at=None,
        ),
    ]
    captured_edges = []
    captured_updates = []

    class FakeEntityNode:
        @staticmethod
        async def get_by_group_ids(driver, group_ids):
            return nodes

    class FakeDriver:
        async def execute_query(self, query, **kwargs):
            if "player_updates" in kwargs:
                captured_updates.extend(kwargs["player_updates"])
            if "edges" in kwargs:
                captured_edges.extend(kwargs["edges"])
            return [], None, None

    def fake_execute_graphiti(coro_factory):
        return coro_factory(SimpleNamespace(driver=FakeDriver()))

    def fake_run_async(awaitable):
        return asyncio.run(awaitable)

    chunk = """
### 墨西哥（Mexico）

#### 球员详情

- 13号，Guillermo Ochoa（GK；40岁；国家队152场/0球；俱乐部：AEL Limassol）
"""

    monkeypatch.setattr(builder_module, "GraphitiEntityNode", FakeEntityNode)
    monkeypatch.setattr(builder_module, "execute_graphiti", fake_execute_graphiti)
    monkeypatch.setattr(builder_module, "run_async", fake_run_async)

    GraphitiGraphBuilderService()._backfill_deterministic_edges(
        "graph_1",
        [chunk],
        ["episode-1"],
    )

    edge_pairs = {
        (edge["source_uuid"], edge["target_uuid"], edge["name"])
        for edge in captured_edges
    }
    assert ("player-ochoa", "team-mexico", "PLAYS_FOR") in edge_pairs
    assert ("player-ochoa", "club-ael", "PLAYS_FOR") in edge_pairs
    assert any(update["uuid"] == "player-ochoa" for update in captured_updates)


def test_graphiti_backfills_roster_table_players_to_current_football_team_labels():
    nodes = [
        SimpleNamespace(
            uuid="team-korea",
            name="韩国",
            labels=["Entity", "FootballTeam"],
            summary="",
            attributes={"全名": "韩国国家男子足球队"},
            created_at=None,
        ),
        SimpleNamespace(
            uuid="player-lee",
            name="李在城",
            labels=["Entity", "Player"],
            summary="",
            attributes={"全名": "李在城", "位置": "攻击型中场/中场"},
            created_at=None,
        ),
        SimpleNamespace(
            uuid="player-cho",
            name="赵贤祐",
            labels=["Entity", "Player"],
            summary="",
            attributes={"全名": "赵贤祐", "位置": "门将"},
            created_at=None,
        ),
    ]
    chunk = """
# 2. 球队 A 基础信息：韩国

| 项目 | 信息 |
|---|---|
| 26 人名单 | 金承奎、李在城、赵贤祐。 |

## 韩国预计首发

- GK：赵贤祐 / 金承奎
- AM/CM：李在城
"""

    payload = GraphitiGraphBuilderService()._build_plays_for_backfill_payload(
        graph_id="graph_1",
        nodes=nodes,
        roster_entries=builder_module._extract_roster_entries([chunk]),
        episode_uuids=["episode-1"],
    )

    edge_pairs = {
        (edge["source_uuid"], edge["target_uuid"], edge["name"])
        for edge in payload["edges"]
    }
    assert ("player-lee", "team-korea", "PLAYS_FOR") in edge_pairs
    assert ("player-cho", "team-korea", "PLAYS_FOR") in edge_pairs
    assert any(node["type"] == "Player" for node in payload["nodes"])


def test_graphiti_enforces_edge_ontology_preserves_non_ontology_edges_by_default(monkeypatch):
    captured_queries = []
    captured_kwargs = []

    class FakeDriver:
        async def execute_query(self, query, **kwargs):
            captured_queries.append(query)
            captured_kwargs.append(kwargs)
            if "renames" in kwargs:
                return [{"renamed_count": 1}], None, None
            if "allowed_edge_names" in kwargs:
                return [{"normalized_count": 1}], None, None
            return [{"non_ontology_edge_count": 3}], None, None

    def fake_execute_graphiti(coro_factory):
        return coro_factory(SimpleNamespace(driver=FakeDriver()))

    def fake_run_async(awaitable):
        return asyncio.run(awaitable)

    monkeypatch.setattr(
        builder_module,
        "load_graph_metadata",
        lambda graph_id: {
            "ontology": {
                "edge_types": [
                    {"name": "PLAYS_FOR"},
                    {"name": "FACES_OFF_AGAINST"},
                ]
            }
        },
    )
    monkeypatch.setattr(builder_module.Config, "GRAPHITI_DELETE_NON_ONTOLOGY_EDGES", False)
    monkeypatch.setattr(builder_module, "execute_graphiti", fake_execute_graphiti)
    monkeypatch.setattr(builder_module, "run_async", fake_run_async)

    GraphitiGraphBuilderService()._enforce_edge_ontology("graph_1")

    assert captured_kwargs[0]["renames"] == [
        {"from": "FACES_IN_MATCH", "to": "FACES_OFF_AGAINST"}
    ]
    assert captured_kwargs[1]["allowed_edge_names"] == ["PLAYS_FOR", "FACES_OFF_AGAINST"]
    assert set(captured_kwargs[2]["allowed_upper"]) == {"PLAYS_FOR", "FACES_OFF_AGAINST"}
    assert "DELETE r" not in captured_queries[2]


def test_graphiti_enforces_edge_ontology_deletes_only_when_configured(monkeypatch):
    captured_queries = []
    captured_kwargs = []

    class FakeDriver:
        async def execute_query(self, query, **kwargs):
            captured_queries.append(query)
            captured_kwargs.append(kwargs)
            if "allowed_edge_names" in kwargs:
                return [{"normalized_count": 0}], None, None
            return [{"deleted_count": 3}], None, None

    def fake_execute_graphiti(coro_factory):
        return coro_factory(SimpleNamespace(driver=FakeDriver()))

    def fake_run_async(awaitable):
        return asyncio.run(awaitable)

    monkeypatch.setattr(
        builder_module,
        "load_graph_metadata",
        lambda graph_id: {
            "ontology": {
                "edge_types": [
                    {"name": "PLAYS_FOR"},
                    {"name": "PARTICIPATES_IN"},
                ]
            }
        },
    )
    monkeypatch.setattr(builder_module.Config, "GRAPHITI_DELETE_NON_ONTOLOGY_EDGES", True)
    monkeypatch.setattr(builder_module, "execute_graphiti", fake_execute_graphiti)
    monkeypatch.setattr(builder_module, "run_async", fake_run_async)

    GraphitiGraphBuilderService()._enforce_edge_ontology("graph_1")

    assert captured_kwargs[0]["allowed_edge_names"] == ["PLAYS_FOR", "PARTICIPATES_IN"]
    assert set(captured_kwargs[1]["allowed_upper"]) == {"PLAYS_FOR", "PARTICIPATES_IN"}
    assert "DELETE r" in captured_queries[1]


def test_graphiti_node_attributes_are_sanitized_for_neo4j():
    node = SimpleNamespace(
        name="2026年世界杯",
        summary="",
        attributes={
            "summary": {
                "description": "Summary containing the important information about the entity.",
                "title": "Summary",
                "type": "string",
                "value": "2026年世界杯是国际足联主办的赛事。",
            },
            "org_name": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "组织名称",
                "title": "Org Name",
                "value": "2026年世界杯",
            },
            "type": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "组织类型",
                "title": "Type",
                "value": "Event",
            },
            "schema_only": {
                "description": "没有真实值的 schema 片段",
                "title": "Schema Only",
                "type": "string",
            },
            "metadata": {"source": "LLM", "confidence": 0.8},
            "aliases": ["FIFA World Cup", {"value": "世界杯"}],
            "nested": [["a", "b"]],
        },
    )

    changed_count = sanitize_graphiti_entity_nodes_for_neo4j([node])

    assert changed_count == 1
    assert node.summary == "2026年世界杯是国际足联主办的赛事。"
    assert node.attributes == {
        "org_name": "2026年世界杯",
        "type": "Event",
        "metadata": '{"source":"LLM","confidence":0.8}',
        "aliases": ["FIFA World Cup", "世界杯"],
        "nested": ['["a","b"]'],
    }


def test_graphiti_bulk_writer_patch_sanitizes_nodes_before_original_call(monkeypatch):
    import graphiti_core.graphiti as graphiti_module
    import graphiti_core.utils.bulk_utils as bulk_utils

    captured_nodes = []

    async def fake_add_nodes_and_edges_bulk(
        driver,
        episodic_nodes,
        episodic_edges,
        entity_nodes,
        entity_edges,
        embedder,
    ):
        captured_nodes.extend(entity_nodes)
        return "written"

    monkeypatch.setattr(graphiti_module, "add_nodes_and_edges_bulk", fake_add_nodes_and_edges_bulk)
    monkeypatch.setattr(bulk_utils, "add_nodes_and_edges_bulk", fake_add_nodes_and_edges_bulk)

    install_graphiti_neo4j_property_sanitizer()

    node = SimpleNamespace(
        name="FIFA",
        summary=None,
        attributes={
            "summary": {"value": "FIFA 负责公布名单版本。"},
            "org_name": {"value": "FIFA"},
            "labels": ["should", "not", "override"],
        },
    )

    result = asyncio.run(
        graphiti_module.add_nodes_and_edges_bulk(
            None,
            [],
            [],
            [node],
            [],
            None,
        )
    )

    assert result == "written"
    assert captured_nodes[0].summary == "FIFA 负责公布名单版本。"
    assert captured_nodes[0].attributes == {"org_name": "FIFA"}


def test_graphiti_get_graph_data_returns_empty_graph_when_no_nodes(monkeypatch):
    class FakeEntityNode:
        @staticmethod
        async def get_by_group_ids(driver, group_ids):
            raise GroupsNodesNotFoundError(group_ids)

    class FakeEntityEdge:
        @staticmethod
        async def get_by_group_ids(driver, group_ids):
            raise AssertionError("edges should not be fetched when nodes are missing")

    def fake_execute_graphiti(coro_factory):
        return coro_factory(SimpleNamespace(driver=object()))

    def fake_run_async(awaitable):
        return asyncio.run(awaitable)

    monkeypatch.setattr(builder_module, "GraphitiEntityNode", FakeEntityNode)
    monkeypatch.setattr(builder_module, "EntityEdge", FakeEntityEdge)
    monkeypatch.setattr(builder_module, "execute_graphiti", fake_execute_graphiti)
    monkeypatch.setattr(builder_module, "run_async", fake_run_async)

    graph_data = GraphitiGraphBuilderService().get_graph_data("graph_empty")

    assert graph_data == {
        "graph_id": "graph_empty",
        "nodes": [],
        "edges": [],
        "node_count": 0,
        "edge_count": 0,
    }


def test_graphiti_get_graph_data_returns_empty_edges_when_no_edges(monkeypatch):
    node = SimpleNamespace(
        uuid="node-1",
        name="FIFA",
        labels=["Organization", "Entity"],
        summary="",
        attributes={},
        created_at=None,
    )

    class FakeEntityNode:
        @staticmethod
        async def get_by_group_ids(driver, group_ids):
            return [node]

    class FakeEntityEdge:
        @staticmethod
        async def get_by_group_ids(driver, group_ids):
            raise GroupsEdgesNotFoundError(group_ids)

    def fake_execute_graphiti(coro_factory):
        return coro_factory(SimpleNamespace(driver=object()))

    def fake_run_async(awaitable):
        return asyncio.run(awaitable)

    monkeypatch.setattr(builder_module, "GraphitiEntityNode", FakeEntityNode)
    monkeypatch.setattr(builder_module, "EntityEdge", FakeEntityEdge)
    monkeypatch.setattr(builder_module, "execute_graphiti", fake_execute_graphiti)
    monkeypatch.setattr(builder_module, "run_async", fake_run_async)

    graph_data = GraphitiGraphBuilderService().get_graph_data("graph_without_edges")

    assert graph_data["node_count"] == 1
    assert graph_data["edge_count"] == 0
    assert graph_data["edges"] == []


def test_graph_build_persists_graph_id_while_task_is_processing(monkeypatch):
    saved_projects = []
    project = Project(
        project_id="proj_dynamic_preview",
        name="Dynamic Preview",
        status=ProjectStatus.ONTOLOGY_GENERATED,
        created_at="2026-06-02T00:00:00",
        updated_at="2026-06-02T00:00:00",
        ontology={"entity_types": [], "edge_types": []},
    )

    class FakeBuilder:
        def create_graph(self, name):
            return "graph_created_early"

        def set_ontology(self, graph_id, ontology):
            saved_after_create = [
                saved.graph_id
                for saved in saved_projects
                if saved.status == ProjectStatus.GRAPH_BUILDING
            ]
            assert "graph_created_early" in saved_after_create
            raise RuntimeError("stop after verifying early graph_id persistence")

    class FakeThread:
        def __init__(self, target, daemon=False):
            self.target = target
            self.daemon = daemon

        def start(self):
            self.target()

    def fake_save_project(project_to_save):
        saved_projects.append(
            SimpleNamespace(
                status=project_to_save.status,
                graph_id=project_to_save.graph_id,
                graph_build_task_id=project_to_save.graph_build_task_id,
                error=project_to_save.error,
            )
        )

    monkeypatch.setattr(graph_api.Config, "validate", lambda: [])
    monkeypatch.setattr(graph_api.Config, "GRAPH_BUILD_EXECUTOR", "thread")
    monkeypatch.setattr(graph_api.ProjectManager, "get_project", lambda project_id: project)
    monkeypatch.setattr(graph_api.ProjectManager, "save_project", fake_save_project)
    monkeypatch.setattr(graph_api.ProjectManager, "get_extracted_text", lambda project_id: "hello world")
    monkeypatch.setattr(graph_api, "get_graph_builder", lambda: FakeBuilder())
    monkeypatch.setattr(graph_api.threading, "Thread", FakeThread)

    app = Flask(__name__)
    with app.test_request_context(json={"project_id": project.project_id}):
        response = graph_api.build_graph().get_json()

    assert response["success"] is True
    assert saved_projects[0].status == ProjectStatus.GRAPH_BUILDING
    assert saved_projects[0].graph_id is None
    assert any(
        saved.status == ProjectStatus.GRAPH_BUILDING and saved.graph_id == "graph_created_early"
        for saved in saved_projects
    )


def test_graph_build_enqueues_celery_when_configured(monkeypatch):
    project = Project(
        project_id="proj_celery",
        name="Celery Graph",
        status=ProjectStatus.ONTOLOGY_GENERATED,
        created_at="2026-06-03T00:00:00",
        updated_at="2026-06-03T00:00:00",
        ontology={"entity_types": [], "edge_types": []},
    )
    saved_projects = []
    enqueued_payloads = []

    class UnexpectedThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError("celery executor should not start a local thread")

    def fake_save_project(project_to_save):
        saved_projects.append(
            SimpleNamespace(
                status=project_to_save.status,
                graph_build_task_id=project_to_save.graph_build_task_id,
            )
        )

    def fake_enqueue_workflow_event(*, event_type, payload, task_id, attempt_id, event_id=None):
        enqueued_payloads.append(
            {
                "event_type": event_type,
                "payload": payload,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "event_id": event_id,
            }
        )
        return {
            "id": "job-1",
            "celery_task_id": "celery-task-1",
            "status": "queued",
        }

    monkeypatch.setattr(graph_api.Config, "validate", lambda: [])
    monkeypatch.setattr(graph_api.Config, "GRAPH_BUILD_EXECUTOR", "celery")
    monkeypatch.setattr(graph_api.ProjectManager, "get_project", lambda project_id: project)
    monkeypatch.setattr(graph_api.ProjectManager, "save_project", fake_save_project)
    monkeypatch.setattr(graph_api.ProjectManager, "get_extracted_text", lambda project_id: "hello world")
    monkeypatch.setattr(graph_api.threading, "Thread", UnexpectedThread)
    monkeypatch.setattr(graph_api, "enqueue_workflow_event", fake_enqueue_workflow_event)
    monkeypatch.setattr(
        graph_api,
        "try_workflow",
        lambda operation, callback: {
            "id": "workflow-task-1",
            "active_attempt": {"id": "attempt-1"},
        },
    )

    app = Flask(__name__)
    with app.test_request_context(json={"project_id": project.project_id}):
        response = graph_api.build_graph().get_json()

    assert response["success"] is True
    assert response["data"]["executor"] == "celery"
    assert response["data"]["celery_task_id"] == "celery-task-1"
    assert enqueued_payloads[0]["event_type"] == "build_match_graph"
    assert enqueued_payloads[0]["payload"]["project_id"] == "proj_celery"
    assert enqueued_payloads[0]["payload"]["legacy_task_id"] == response["data"]["task_id"]
    assert saved_projects[-1].status == ProjectStatus.GRAPH_BUILDING
