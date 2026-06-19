from app.utils import llm_client as llm_client_module
from app.utils.llm_client import LLMClient


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    finish_reason = "stop"

    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    usage = None

    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


def _fake_openai_factory(contents):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return _FakeResponse(contents.pop(0))

    class FakeChat:
        def __init__(self):
            self.completions = FakeCompletions()

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.chat = FakeChat()

    return FakeOpenAI, calls


def test_chat_json_sends_response_format_when_json_object_mode_supported(monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_FORMAT_JSON_OBJECT_SUPPORTED", "true")
    fake_openai, calls = _fake_openai_factory(['{"ok": true}'])
    monkeypatch.setattr(llm_client_module, "OpenAI", fake_openai)

    client = LLMClient(
        api_key="placeholder-key",
        base_url="https://api.example.com/v1",
        model="test-model",
    )

    assert client.chat_json([{"role": "user", "content": "Return JSON"}]) == {"ok": True}
    assert calls[0]["response_format"] == {"type": "json_object"}


def test_chat_json_omits_response_format_and_adds_prompt_constraint_when_disabled(monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_FORMAT_JSON_OBJECT_SUPPORTED", "false")
    fake_openai, calls = _fake_openai_factory(['{"ok": true}'])
    monkeypatch.setattr(llm_client_module, "OpenAI", fake_openai)

    client = LLMClient(
        api_key="placeholder-key",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        model="deepseek-v4-pro",
    )

    assert client.chat_json([{"role": "user", "content": "Return JSON"}]) == {"ok": True}
    assert "response_format" not in calls[0]
    assert calls[0]["messages"][0]["role"] == "system"
    assert "JSON" in calls[0]["messages"][0]["content"]
    assert "不要输出 Markdown" in calls[0]["messages"][0]["content"]


def test_chat_json_repairs_invalid_json_when_response_format_disabled(monkeypatch):
    monkeypatch.setenv("LLM_RESPONSE_FORMAT_JSON_OBJECT_SUPPORTED", "false")
    fake_openai, calls = _fake_openai_factory(["not json", '{"ok": true}'])
    monkeypatch.setattr(llm_client_module, "OpenAI", fake_openai)

    client = LLMClient(
        api_key="placeholder-key",
        base_url="https://ark.cn-beijing.volces.com/api/coding/v3",
        model="deepseek-v4-pro",
    )

    assert client.chat_json([{"role": "user", "content": "Return JSON"}]) == {"ok": True}
    assert len(calls) == 2
    assert "response_format" not in calls[0]
    assert "response_format" not in calls[1]
    assert "not json" in calls[1]["messages"][1]["content"]
