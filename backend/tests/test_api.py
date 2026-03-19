from __future__ import annotations

import os

os.environ["ASSISTANT_STORE_BACKEND"] = "memory"

from fastapi.testclient import TestClient

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
    assert upload.json()["data"]["processing_status"] == "READY"

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

    knowledge = client.put(
        "/api/v1/settings/knowledge",
        json={
            "chunk_size": 800,
            "chunk_overlap": 100,
            "retrieval_top_k": 4,
            "relevance_threshold": 0.1,
            "hybrid_search_enabled": True,
            "rag_template": "Use context carefully.",
        },
    )
    assert knowledge.status_code == 200
    assert knowledge.json()["data"]["chunk_size"] == 800

    system = client.put(
        "/api/v1/settings/system",
        json={"app_name": "Assistant", "theme": "dark"},
    )
    assert system.status_code == 200
    assert system.json()["data"]["theme"] == "dark"
