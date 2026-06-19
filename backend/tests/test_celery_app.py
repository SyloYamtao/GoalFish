import importlib

from app.utils import llm_logging


def test_celery_app_installs_llm_completion_logging(monkeypatch):
    calls = []

    monkeypatch.setattr(
        llm_logging,
        "install_llm_completion_logging",
        lambda: calls.append(True),
    )

    import app.celery_app as celery_app_module

    importlib.reload(celery_app_module)

    assert calls


def test_celery_does_not_wrap_stdout_as_warning():
    import app.celery_app as celery_app_module

    assert celery_app_module.celery_app.conf.worker_redirect_stdouts is False
