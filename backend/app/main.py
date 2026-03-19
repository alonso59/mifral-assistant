from __future__ import annotations

import json
from collections.abc import Generator
from typing import Optional

from fastapi import FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.models import EmbeddingProvider, GenerationProvider, KnowledgeSettings, ModelSettings, SystemSettings
from app.store import store


def success(data, meta=None):  # type: ignore[no-untyped-def]
    payload = {"data": data}
    if meta is not None:
        payload["meta"] = meta
    return payload


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def require_session_id(x_session_id: Optional[str]) -> str:
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-Id header is required.")
    return x_session_id


class RenameChatRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class MessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class CreateSpaceRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)


class SelectSpaceRequest(BaseModel):
    chat_id: str


class UpdateGenerationSettingsRequest(BaseModel):
    provider: GenerationProvider
    model: str = Field(min_length=1, max_length=255)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=64, le=32768)
    context_max_tokens: int = Field(default=8192, ge=512, le=131072)
    auto_compress: bool = False


class UpdateEmbeddingSettingsRequest(BaseModel):
    provider: EmbeddingProvider
    model: str = Field(min_length=1, max_length=255)
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class UpdateModelSettingsRequest(BaseModel):
    generation: UpdateGenerationSettingsRequest
    embedding: UpdateEmbeddingSettingsRequest


class UpdateKnowledgeSettingsRequest(BaseModel):
    chunk_size: int
    chunk_overlap: int
    retrieval_top_k: int
    relevance_threshold: float
    hybrid_search_enabled: bool
    rag_template: str


class UpdateSystemSettingsRequest(BaseModel):
    app_name: str
    theme: str


app = FastAPI(title="Assistant Backend", version="0.1.0")


@app.get("/")
def root() -> dict:
    return {"status": "ok", "service": "assistant-backend"}


@app.get("/api/v1/chats")
def list_chats(x_session_id: Optional[str] = Header(default=None)) -> dict:
    session_id = require_session_id(x_session_id)
    return success([chat.model_dump() for chat in store.list_chats(session_id)])


@app.post("/api/v1/chats", status_code=201)
def create_chat(x_session_id: Optional[str] = Header(default=None)) -> dict:
    session_id = require_session_id(x_session_id)
    return success(store.create_chat(session_id).model_dump())


@app.get("/api/v1/chats/{chat_id}/messages")
def get_messages(chat_id: str, x_session_id: Optional[str] = Header(default=None)) -> dict:
    session_id = require_session_id(x_session_id)
    return success([msg.model_dump() for msg in store.list_messages(session_id, chat_id)])


@app.patch("/api/v1/chats/{chat_id}")
def rename_chat(chat_id: str, body: RenameChatRequest, x_session_id: Optional[str] = Header(default=None)) -> dict:
    session_id = require_session_id(x_session_id)
    return success(store.rename_chat(session_id, chat_id, body.title).model_dump())


@app.delete("/api/v1/chats/{chat_id}")
def delete_chat(chat_id: str, x_session_id: Optional[str] = Header(default=None)) -> dict:
    session_id = require_session_id(x_session_id)
    store.delete_chat(session_id, chat_id)
    return success({"deleted": True})


def _stream_reply(session_id: str, chat_id: str, message: str) -> Generator[str, None, None]:
    user_message = store.append_user_message(session_id, chat_id, message)
    assistant_message = store.append_assistant_message(session_id, chat_id, message)
    yield sse({"type": "start", "chat_id": chat_id})
    yield sse({"type": "message", "message": user_message.model_dump()})
    yield sse({"type": "message", "message": assistant_message.model_dump()})
    if assistant_message.citations:
        yield sse({"type": "sources", "items": [citation.model_dump() for citation in assistant_message.citations]})
    yield sse({"type": "done"})


@app.post("/api/v1/chats/{chat_id}/messages/stream")
def send_message(
    chat_id: str,
    body: MessageRequest,
    x_session_id: Optional[str] = Header(default=None),
) -> StreamingResponse:
    session_id = require_session_id(x_session_id)
    return StreamingResponse(_stream_reply(session_id, chat_id, body.message), media_type="text/event-stream")


@app.post("/api/v1/chats/{chat_id}/regenerate")
def regenerate(chat_id: str, x_session_id: Optional[str] = Header(default=None)) -> StreamingResponse:
    session_id = require_session_id(x_session_id)

    def generator() -> Generator[str, None, None]:
        message = store.regenerate(session_id, chat_id)
        yield sse({"type": "start", "chat_id": chat_id})
        yield sse({"type": "message", "message": message.model_dump()})
        if message.citations:
            yield sse({"type": "sources", "items": [citation.model_dump() for citation in message.citations]})
        yield sse({"type": "done"})

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.delete("/api/v1/chats/{chat_id}/knowledge-selection")
def clear_knowledge(chat_id: str, x_session_id: Optional[str] = Header(default=None)) -> dict:
    session_id = require_session_id(x_session_id)
    return success(store.clear_selection(session_id, chat_id).model_dump())


@app.get("/api/v1/knowledge-spaces")
def list_spaces() -> dict:
    return success(store.list_spaces())


@app.post("/api/v1/knowledge-spaces", status_code=201)
def create_space(body: CreateSpaceRequest) -> dict:
    return success(store.create_space(body.name, body.description).model_dump())


@app.patch("/api/v1/knowledge-spaces/{space_id}")
def update_space(space_id: str, body: CreateSpaceRequest) -> dict:
    return success(store.update_space(space_id, body.name, body.description).model_dump())


@app.delete("/api/v1/knowledge-spaces/{space_id}")
def delete_space(space_id: str) -> dict:
    store.delete_space(space_id)
    return success({"deleted": True})


@app.post("/api/v1/knowledge-spaces/{space_id}/documents", status_code=201)
async def upload_document(space_id: str, file: UploadFile = File(...)) -> dict:
    row = await store.add_document(space_id, file)
    return success(row.model_dump())


@app.post("/api/v1/knowledge-spaces/{space_id}/select")
def select_space(
    space_id: str,
    body: SelectSpaceRequest,
    x_session_id: Optional[str] = Header(default=None),
) -> dict:
    session_id = require_session_id(x_session_id)
    return success(store.select_space(session_id, body.chat_id, space_id).model_dump())


@app.get("/api/v1/settings/model")
def get_model_settings() -> dict:
    return success(store.get_model_settings().model_dump())


@app.put("/api/v1/settings/model")
def put_model_settings(body: UpdateModelSettingsRequest) -> dict:
    settings = ModelSettings(
        generation={
            "provider": body.generation.provider,
            "model": body.generation.model,
            "api_key_set": False,
            "base_url": body.generation.base_url,
            "system_prompt": body.generation.system_prompt,
            "temperature": body.generation.temperature,
            "max_tokens": body.generation.max_tokens,
            "context_max_tokens": body.generation.context_max_tokens,
            "auto_compress": body.generation.auto_compress,
        },
        embedding={
            "provider": body.embedding.provider,
            "model": body.embedding.model,
            "api_key_set": False,
            "base_url": body.embedding.base_url,
        },
    )

    if hasattr(store, "set_model_settings"):
        if store.__class__.__name__ == "PostgresAssistantStore":
            data = store.set_model_settings(
                settings,
                generation_api_key=body.generation.api_key,
                embedding_api_key=body.embedding.api_key,
            )
        else:
            data = store.set_model_settings(
                ModelSettings(
                    generation={
                        **settings.generation.model_dump(),
                        "api_key_set": bool(body.generation.api_key),
                    },
                    embedding={
                        **settings.embedding.model_dump(),
                        "api_key_set": bool(body.embedding.api_key),
                    },
                )
            )
    else:
        data = settings
    return success(data.model_dump())


@app.get("/api/v1/settings/model/ollama/models")
def get_ollama_models(base_url: Optional[str] = Query(default=None)) -> dict:
    try:
        return success(store.get_ollama_models(base_url))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Cannot reach Ollama: {exc}") from exc


@app.get("/api/v1/settings/knowledge")
def get_knowledge_settings() -> dict:
    return success(store.get_knowledge_settings().model_dump())


@app.put("/api/v1/settings/knowledge")
def put_knowledge_settings(body: UpdateKnowledgeSettingsRequest) -> dict:
    return success(store.set_knowledge_settings(KnowledgeSettings(**body.model_dump())).model_dump())


@app.get("/api/v1/settings/system")
def get_system_settings() -> dict:
    return success(store.get_system_settings().model_dump())


@app.put("/api/v1/settings/system")
def put_system_settings(body: UpdateSystemSettingsRequest) -> dict:
    return success(store.set_system_settings(SystemSettings(**body.model_dump())).model_dump())
