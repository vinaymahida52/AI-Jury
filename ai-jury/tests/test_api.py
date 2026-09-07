import json

import pytest
from fastapi.testclient import TestClient

from aijury.api.server import create_app


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def test_health_reports_configuration(client, settings):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["provider"] == settings.provider
    assert body["max_jurors"] == settings.budget.max_jurors


def test_ask_returns_full_record(client):
    body = client.post("/api/ask", json={"question": "Should we adopt event sourcing?"}).json()
    assert body["verdict"]["answer"]
    assert body["positions"], "the record must expose per-round positions"
    assert 0.0 <= body["verified_ratio"] <= 1.0
    assert body["budget"]["llm_calls"] > 0


def test_ask_rejects_empty_question(client):
    assert client.post("/api/ask", json={"question": "   "}).status_code in (400, 422)


def test_ask_honours_per_request_overrides(client):
    body = client.post(
        "/api/ask", json={"question": "A question?", "max_rounds": 1, "max_jurors": 2}
    ).json()
    assert body["verdict"]["rounds_used"] == 1
    assert len(body["verdict"]["jurors"]) <= 3  # jurors + adversary


def test_ask_accepts_single_round_and_single_juror(client):
    body = client.post(
        "/api/ask", json={"question": "A question?", "max_rounds": 1, "max_jurors": 1}
    ).json()
    assert body["verdict"]["rounds_used"] == 1
    assert body["verdict"]["answer"]


def test_ask_rejects_non_positive_panel_shape(client):
    assert client.post(
        "/api/ask", json={"question": "A question?", "max_rounds": 0}
    ).status_code == 422
    assert client.post(
        "/api/ask", json={"question": "A question?", "max_jurors": 0}
    ).status_code == 422


def test_verdict_in_api_carries_no_transcript(client):
    """The API's Verdict must honour the results-only contract."""
    body = client.post("/api/ask", json={"question": "What should we do?"}).json()
    assert "positions" not in body["verdict"]
    assert "messages" not in body["verdict"]


def test_stream_emits_spans_then_verdict(client):
    with client.stream(
        "GET", "/api/stream", params={"question": "Is streaming wired up?"}
    ) as response:
        assert response.status_code == 200
        events = [
            line[len("event: "):]
            for line in response.iter_lines()
            if line.startswith("event: ")
        ]
    assert events[0] == "open"
    assert "span" in events
    assert "verdict" in events
    assert events[-1] == "done"


def test_stream_emits_live_chamber_before_the_verdict(client):
    with client.stream(
        "GET", "/api/stream", params={"question": "Is the chamber wired?"}
    ) as response:
        events = [
            line[len("event: "):]
            for line in response.iter_lines()
            if line.startswith("event: ")
        ]
    assert "live" in events
    assert events.index("live") < events.index("verdict")


def test_stream_greets_without_convening_the_panel(client):
    with client.stream("GET", "/api/stream", params={"question": "hello"}) as response:
        assert response.status_code == 200
        lines = list(response.iter_lines())
    events = [line[len("event: "):] for line in lines if line.startswith("event: ")]
    payloads = [
        json.loads(line[len("data: "):]) for line in lines if line.startswith("data: ")
    ]
    assert "chat" in events
    assert "verdict" not in events
    assert "span" not in events
    replies = [p.get("reply") for p in payloads if isinstance(p, dict) and p.get("reply")]
    assert replies == ["Hello."]


def test_stream_reports_errors_without_hanging(client):
    with client.stream("GET", "/api/stream", params={"question": "x" * 25_000}) as response:
        assert response.status_code == 422


def test_index_serves_the_console(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AI Jury" in response.text


def test_console_does_not_expose_round_or_juror_controls(client):
    html = client.get("/").text
    assert 'id="chamber"' in html
    assert 'id="clock"' in html
    assert 'id="dock"' in html
    assert 'id="dock-toggle"' in html
    assert "HCNSEC" in html
    assert 'id="gw-label"' in html
    assert 'id="rounds"' not in html
    assert 'id="jurors"' not in html
    assert "max_rounds=" not in html
    assert "max_jurors=" not in html


def test_gateways_catalog_includes_presets(client):
    body = client.get("/api/gateways").json()
    assert body["active"] == "mock"
    ids = {p["id"] for p in body["presets"]}
    assert "hcnsec" in ids and "tokenera" in ids


def test_save_and_seat_gateway_updates_health(client):
    saved = client.put(
        "/api/gateways",
        json={
            "id": "tokenera",
            "label": "Tokenera",
            "base_url": "https://tokenera.example/v1",
            "model": "tk-1",
            "api_key": "sk-test-not-real",
            "seat": True,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["gateway"]["key_set"] is True
    assert "sk-test-not-real" not in saved.text
    health = client.get("/api/health").json()
    assert health["provider"] == "tokenera"
    assert health["model"] == "tk-1"
    seated = client.post("/api/gateways/mock/seat").json()
    assert seated["provider"] == "mock"
    assert client.get("/api/health").json()["provider"] == "mock"


def test_gateway_probe_lists_models(client, monkeypatch):
    client.put(
        "/api/gateways",
        json={
            "id": "hcnsec",
            "label": "HCNSEC",
            "base_url": "https://api.hcnsec.cn/v1",
            "model": "Qwen3.8-27B",
            "api_key": "sk-test",
        },
    )
    monkeypatch.setattr(
        "aijury.api.server.list_remote_models",
        lambda base_url, api_key: ["Qwen3.8-27B", "other"],
    )
    body = client.post("/api/gateways/hcnsec/probe").json()
    assert body["models"] == ["Qwen3.8-27B", "other"]


def test_streamed_span_payload_is_json(client):
    with client.stream(
        "GET", "/api/stream", params={"question": "Payload shape?", "max_rounds": 1}
    ) as response:
        for line in response.iter_lines():
            if line.startswith("data: "):
                assert isinstance(json.loads(line[len("data: "):]), dict)
                break
