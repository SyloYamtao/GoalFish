from flask import Flask

from app.api import graph as graph_api


def test_generate_ontology_rejects_invalid_simulation_domain_before_creating_project(monkeypatch):
    created_projects = []
    monkeypatch.setattr(
        graph_api.ProjectManager,
        "create_project",
        lambda *args, **kwargs: created_projects.append(True),
    )

    app = Flask(__name__)
    with app.test_request_context(
        "/api/graph/ontology/generate",
        method="POST",
        data={
            "simulation_requirement": "预测男足比赛比分",
            "simulation_domain": "basketball",
        },
    ):
        response, status_code = graph_api.generate_ontology()

    assert status_code == 400
    assert response.get_json()["success"] is False
    assert "Unsupported simulation_domain" in response.get_json()["error"]
    assert created_projects == []
