import io
import os

import run


def test_resolve_console_log_path_uses_startup_time(tmp_path, monkeypatch):
    monkeypatch.delenv("GOALFISH_CONSOLE_LOG_FILE", raising=False)
    monkeypatch.setenv("GOALFISH_STARTUP_TIME", "2026-06-02_18-30-12")

    log_path = run.resolve_console_log_path(str(tmp_path))

    assert log_path == os.path.join(str(tmp_path), "logs", "2026-06-02_18-30-12.log")
    assert os.environ["GOALFISH_CONSOLE_LOG_FILE"] == log_path


def test_resolve_console_log_path_reuses_existing_file(monkeypatch):
    monkeypatch.setenv("GOALFISH_CONSOLE_LOG_FILE", "/tmp/goalfish-existing.log")
    monkeypatch.setenv("GOALFISH_STARTUP_TIME", "2026-06-02_18-30-12")

    assert run.resolve_console_log_path("/ignored") == "/tmp/goalfish-existing.log"


def test_tee_stream_writes_to_console_and_log():
    original = io.StringIO()
    log_file = io.StringIO()
    lock = run.threading.RLock()
    stream = run.TeeStream(original, log_file, lock)

    stream.write("hello\n")
    stream.flush()

    assert original.getvalue() == "hello\n"
    assert log_file.getvalue() == "hello\n"
    assert stream._goalfish_console_tee is True
