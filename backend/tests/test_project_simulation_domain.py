from app.models.project import Project, ProjectStatus


def test_project_defaults_missing_simulation_domain_to_football_match():
    project = Project.from_dict({
        "project_id": "proj_old",
        "name": "旧项目",
        "status": "created",
        "created_at": "2026-06-01T00:00:00",
        "updated_at": "2026-06-01T00:00:00",
        "simulation_requirement": "测试需求",
    })

    assert project.status == ProjectStatus.CREATED
    assert project.simulation_domain == "football_match"
    assert project.to_dict()["simulation_domain"] == "football_match"
