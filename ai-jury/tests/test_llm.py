import pytest
from pydantic import BaseModel

from aijury.llm.base import StructuredParseError, complete_structured, extract_json
from aijury.llm.mock import MockLLMClient


class Sample(BaseModel):
    name: str
    score: float


def test_extract_json_handles_fences_and_preamble():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_handles_braces_in_strings():
    assert extract_json('{"a": "} not the end"}') == {"a": "} not the end"}


def test_extract_json_raises_without_object():
    with pytest.raises(StructuredParseError):
        extract_json("no json here")


async def test_structured_completion_validates_against_schema():
    result, response = await complete_structured(
        MockLLMClient(), Sample, "You produce samples.", "make one"
    )
    assert isinstance(result, Sample) and response.tokens_out > 0


async def test_structured_completion_raises_after_retries():
    class Broken:
        model = "broken"

        async def complete(self, system, prompt, *, max_tokens=2000, temperature=0.7):
            from aijury.llm.base import LLMResponse

            return LLMResponse(text="not json at all", model="broken")

    with pytest.raises(StructuredParseError):
        await complete_structured(Broken(), Sample, "s", "p", retries=1)


async def test_mock_is_deterministic_for_same_seed():
    a = MockLLMClient(seed=3)
    b = MockLLMClient(seed=3)
    ra = await a.complete("JSON schema:\n{}", "same prompt")
    rb = await b.complete("JSON schema:\n{}", "same prompt")
    assert ra.text == rb.text


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Msg(content)


class _Usage:
    prompt_tokens = 11
    completion_tokens = 7


class _Completion:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]
        self.usage = _Usage()


class _FakeOpenAI:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.calls: list[dict] = []

        class _Completions:
            def __init__(self, outer: "_FakeOpenAI") -> None:
                self._outer = outer

            def create(self, **kwargs):
                self._outer.calls.append(kwargs)
                return _Completion(
                    "We need answer user: Explain quantum entanglement.\n"
                    "</think>\n\n"
                    "entanglement is nonlocal correlation"
                )

        class _Chat:
            def __init__(self, outer: "_FakeOpenAI") -> None:
                self.completions = _Completions(outer)

        self.chat = _Chat(self)


def test_extract_assistant_text_drops_qwen_thinking():
    from aijury.llm.openai_client import extract_assistant_text

    raw = (
        "We need answer user: Explain quantum entanglement in one paragraph.\n"
        "</think>\n\n"
        "Quantum entanglement is a phenomenon in which two particles become linked."
    )
    out = extract_assistant_text(raw)
    assert out.startswith("Quantum entanglement")
    assert "</think>" not in out
    assert "We need answer user" not in out


def test_hcnsec_settings_come_from_env(tmp_path, monkeypatch):
    from aijury.config import Settings

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "AIJURY_PROVIDER=hcnsec\n"
        "HCNSEC_API_KEY=test-key-not-real\n"
        "AIJURY_MODEL=Qwen3.8-27B\n"
    )
    monkeypatch.delenv("AIJURY_PROVIDER", raising=False)
    monkeypatch.delenv("HCNSEC_API_KEY", raising=False)
    monkeypatch.delenv("AIJURY_MODEL", raising=False)
    settings = Settings.from_env()
    assert settings.provider == "hcnsec"
    assert settings.hcnsec_api_key == "test-key-not-real"
    assert settings.model == "Qwen3.8-27B"
    assert settings.openai_base_url == "https://api.hcnsec.cn/v1"


def test_build_client_hcnsec_uses_openai_compat(monkeypatch):
    import aijury.llm.openai_client as openai_client
    from aijury.config import Settings
    from aijury.llm.registry import build_client

    monkeypatch.setattr(openai_client, "OpenAI", _FakeOpenAI)
    settings = Settings(
        provider="hcnsec",
        model="Qwen3.8-27B",
        hcnsec_api_key="test-key-not-real",
    )
    client = build_client(settings)
    assert client.model == "Qwen3.8-27B"
    assert client._client.kwargs["base_url"] == "https://api.hcnsec.cn/v1"
    assert client._client.kwargs["api_key"] == "test-key-not-real"


def test_hcnsec_client_requires_api_key():
    from aijury.config import Settings
    from aijury.llm.registry import build_client

    with pytest.raises(RuntimeError, match="API key"):
        build_client(Settings(provider="hcnsec", hcnsec_api_key=""))


async def test_openai_compat_complete_reads_chat_content(monkeypatch):
    from aijury.llm.openai_client import OpenAICompatClient

    fake = _FakeOpenAI(base_url="https://api.hcnsec.cn/v1", api_key="k")
    client = OpenAICompatClient(
        "Qwen3.8-27B",
        api_key="k",
        base_url="https://api.hcnsec.cn/v1",
        seed=7,
        client=fake,
    )
    response = await client.complete("sys", "Explain quantum entanglement in one paragraph.")
    assert "entanglement is nonlocal correlation" in response.text
    assert "</think>" not in response.text
    assert "We need answer user" not in response.text
    assert response.tokens_in == 11
    assert response.tokens_out == 7
    assert fake.calls[0]["model"] == "Qwen3.8-27B"
    assert fake.calls[0]["messages"][0]["role"] == "system"
    assert fake.calls[0]["n"] == 1
    assert fake.calls[0]["stream"] is False
    assert fake.calls[0]["response_format"] == {"type": "json_object"}
    assert fake.calls[0]["top_p"] == 1
    assert fake.calls[0]["frequency_penalty"] == 0
    assert fake.calls[0]["presence_penalty"] == 0
    assert fake.calls[0]["max_tokens"] >= 1
    assert 0 <= fake.calls[0]["temperature"] <= 2
    assert fake.calls[0]["seed"] == 7
