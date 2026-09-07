from aijury.config import Settings
from aijury.llm.gateways import Gateway, GatewayBook, PRESETS, apply_gateway, slug
from aijury.llm.openai_client import OpenAICompatClient
from aijury.llm.registry import build_client


def test_presets_cover_hcnsec_and_tokenera():
    ids = {p.id for p in PRESETS}
    assert {"hcnsec", "tokenera", "openai", "custom"} <= ids


def test_slug_is_stable():
    assert slug("Tokenera") == "tokenera"
    assert slug("My Gateway!!") == "my-gateway"


def test_book_hides_the_raw_key(tmp_path):
    book = GatewayBook(tmp_path / "gateways.json")
    gw = book.upsert(
        label="Tokenera",
        base_url="https://api.example.test/v1",
        model="demo-model",
        api_key="sk-secret-value",
    )
    public = gw.public()
    assert public["key_set"] is True
    assert "sk-secret-value" not in str(public)
    assert public["key_hint"].endswith("alue")
    saved = (tmp_path / "gateways.json").read_text()
    assert "sk-secret-value" in saved  # on disk, for the operator


def test_empty_key_on_update_keeps_the_existing_one(tmp_path):
    book = GatewayBook(tmp_path / "gateways.json")
    book.upsert(
        label="HCNSEC",
        base_url="https://api.hcnsec.cn/v1",
        model="Qwen3.8-27B",
        api_key="keep-me",
        gateway_id="hcnsec",
    )
    again = book.upsert(
        label="HCNSEC",
        base_url="https://api.hcnsec.cn/v1",
        model="Qwen3.8-27B",
        api_key="",
        gateway_id="hcnsec",
    )
    assert again.api_key == "keep-me"


def test_apply_gateway_points_settings_at_the_new_host():
    settings = apply_gateway(
        Settings(provider="mock"),
        Gateway(
            id="tokenera",
            label="Tokenera",
            base_url="https://tokenera.example/v1",
            model="tk-1",
            api_key="k",
        ),
    )
    assert settings.provider == "tokenera"
    assert settings.openai_base_url == "https://tokenera.example/v1"
    assert settings.model == "tk-1"
    assert settings.hcnsec_api_key == "k"


def test_build_client_accepts_any_openai_compat_provider(monkeypatch):
    import aijury.llm.openai_client as openai_client

    class _Fake:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        @property
        def chat(self):
            return self

        @property
        def completions(self):
            return self

    monkeypatch.setattr(openai_client, "OpenAI", _Fake)
    settings = Settings(
        provider="tokenera",
        model="tk-1",
        hcnsec_api_key="k",
        openai_base_url="https://tokenera.example/v1",
    )
    client = build_client(settings)
    assert isinstance(client, OpenAICompatClient)
    assert client._client.kwargs["base_url"] == "https://tokenera.example/v1"
