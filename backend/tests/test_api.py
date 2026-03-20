from __future__ import annotations

import os

os.environ["ASSISTANT_STORE_BACKEND"] = "memory"

from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.generation import check_ollama_health, normalize_ollama_base_url
from app.main import app


client = TestClient(app)
HEADERS = {"X-Session-Id": "session-a"}


def test_chat_lifecycle_and_knowledge_selection() -> None:
    created = client.post("/api/v1/chats", headers=HEADERS)
    assert created.status_code == 201
    chat_id = created.json()["data"]["id"]

    space = client.post(
        "/api/v1/knowledge-spaces",
        json={"name": "Product Docs", "description": "Source material"},
    )
    assert space.status_code == 201
    space_id = space.json()["data"]["id"]

    upload = client.post(
        f"/api/v1/knowledge-spaces/{space_id}/documents",
        files={"file": ("guide.txt", b"pgvector stores embeddings for retrieval", "text/plain")},
    )
    assert upload.status_code == 201
    assert upload.json()["data"]["processing_status"] == "PENDING"
    assert upload.json()["data"]["processing_stage"] == "QUEUED"
    assert upload.json()["data"]["processing_progress_percent"] == 0

    spaces = client.get("/api/v1/knowledge-spaces")
    assert spaces.status_code == 200
    uploaded_document = spaces.json()["data"][0]["documents"][0]
    assert uploaded_document["processing_status"] == "READY"
    assert uploaded_document["processing_stage"] == "READY"
    assert uploaded_document["processing_progress_percent"] == 100
    assert uploaded_document["processing_message"] == "Ready for grounded chat."

    selected = client.post(
        f"/api/v1/knowledge-spaces/{space_id}/select",
        headers=HEADERS,
        json={"chat_id": chat_id},
    )
    assert selected.status_code == 200
    assert selected.json()["data"]["knowledge_space_id"] == space_id

    response = client.post(
        f"/api/v1/chats/{chat_id}/messages/stream",
        headers=HEADERS,
        json={"message": "How does pgvector help retrieval?"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"type": "token"' in response.text
    assert '"type": "grounded"' in response.text
    assert '"type": "sources"' in response.text

    messages = client.get(f"/api/v1/chats/{chat_id}/messages", headers=HEADERS)
    assert messages.status_code == 200
    assert len(messages.json()["data"]) == 2
    assert messages.json()["data"][1]["grounded"] is True

    cleared = client.delete(f"/api/v1/chats/{chat_id}/knowledge-selection", headers=HEADERS)
    assert cleared.status_code == 200
    assert cleared.json()["data"]["knowledge_space_id"] is None


def test_settings_roundtrip_and_chat_isolated_by_session() -> None:
    created = client.post("/api/v1/chats", headers=HEADERS)
    chat_id = created.json()["data"]["id"]

    other_session = client.get("/api/v1/chats", headers={"X-Session-Id": "session-b"})
    assert all(chat["id"] != chat_id for chat in other_session.json()["data"])

    model = client.put(
        "/api/v1/settings/model",
        json={
            "generation": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key": "sk-test",
                "base_url": "https://api.openai.com/v1",
                "system_prompt": "You are a helpful AI assistant.",
                "temperature": 0.5,
                "max_tokens": 1024,
                "context_max_tokens": 8192,
                "auto_compress": False,
            },
            "embedding": {
                "provider": "google",
                "model": "models/text-embedding-004",
                "api_key": "google-key",
                "base_url": None,
            },
        },
    )
    assert model.status_code == 200
    assert model.json()["data"]["generation"]["provider"] == "openai"
    assert model.json()["data"]["embedding"]["provider"] == "google"

    ollama_models = client.get("/api/v1/settings/model/ollama/models")
    assert ollama_models.status_code == 200
    assert len(ollama_models.json()["data"]) >= 1

    ollama_health = client.get("/api/v1/settings/model/ollama/health")
    assert ollama_health.status_code == 200
    assert ollama_health.json()["data"]["ok"] is True

    ollama_pull = client.post(
        "/api/v1/settings/model/ollama/pull",
        json={"model": "llama3.2"},
    )
    assert ollama_pull.status_code == 200
    assert ollama_pull.headers["content-type"].startswith("text/event-stream")
    assert '"status": "success"' in ollama_pull.text

    knowledge = client.put(
        "/api/v1/settings/knowledge",
        json={
            "chunk_size": 800,
            "chunk_overlap": 100,
            "retrieval_top_k": 4,
            "relevance_threshold": 0.1,
            "enable_markdown_chunking": True,
            "query_augmentation": True,
            "hybrid_search_enabled": True,
            "hybrid_bm25_weight": 0.35,
            "rag_template": "Use context carefully.",
        },
    )
    assert knowledge.status_code == 200
    assert knowledge.json()["data"]["chunk_size"] == 800
    assert knowledge.json()["data"]["query_augmentation"] is True

    system = client.put(
        "/api/v1/settings/system",
        json={"app_name": "Assistant", "theme": "dark", "show_thinking_overlay": False},
    )
    assert system.status_code == 200
    assert system.json()["data"]["theme"] == "dark"
    assert system.json()["data"]["show_thinking_overlay"] is False


def test_openrouter_models_fallback_and_stream_contract() -> None:
    models = client.get("/api/v1/settings/model/openrouter/models")
    assert models.status_code == 200
    assert models.json()["data"][0]["id"] == "nvidia/nemotron-3-super-120b-a12b:free"
    assert models.json()["data"][0]["supports_reasoning"] is True


def test_ollama_helpers_reject_openrouter_urls() -> None:
    try:
        check_ollama_health("https://openrouter.ai/api/v1")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Ollama" in str(exc.detail)
    else:
        raise AssertionError("Expected OpenRouter URL to be rejected for Ollama health checks.")


def test_ollama_https_url_is_normalized_to_http() -> None:
    assert normalize_ollama_base_url("https://ollama:11434") == "http://ollama:11434"
    assert normalize_ollama_base_url("https://localhost:11434") == "http://localhost:11434"


def test_ollama_localhost_rewrites_only_inside_docker(monkeypatch) -> None:
    monkeypatch.setenv("RUNNING_IN_DOCKER", "1")
    monkeypatch.delenv("OLLAMA_DOCKER_HOST", raising=False)
    assert normalize_ollama_base_url("http://localhost:11434") == "http://host.docker.internal:11434"
