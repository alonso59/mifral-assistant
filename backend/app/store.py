from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import HTTPException

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except ModuleNotFoundError:  # pragma: no cover - optional in memory-only test runs
    psycopg2 = None
    Json = None
    RealDictCursor = None

from app.embedding import build_embedding_provider
from app.generation import (
    OPENROUTER_DEFAULT_MODEL,
    build_generation_provider,
    check_ollama_health,
    list_ollama_models,
    list_openrouter_models,
    pull_ollama_model,
)
from app.generation_protocol import GenerationEvent
from app.models import (
    EMBEDDING_PROVIDER_OPTIONS,
    GENERATION_PROVIDER_OPTIONS,
    Chat,
    ChatMessage,
    Citation,
    EmbeddingSettings,
    FeedbackVote,
    GenerationSettings,
    KnowledgeDocument,
    KnowledgeSettings,
    KnowledgeSpace,
    ModelSettings,
    ProviderModelOption,
    SystemSettings,
)


DEFAULT_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
DEFAULT_EMBEDDING_MODEL = os.getenv(
    "ASSISTANT_EMBED_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
DEFAULT_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://assistant:assistant@postgres:5432/assistant",
)
LOCAL_OLLAMA_HOSTS = {"ollama", "localhost", "127.0.0.1", "::1", "host.docker.internal"}
IN_PROGRESS_DOCUMENT_STATUSES = {"PENDING", "PROCESSING"}
DOCUMENT_STAGE_STATE: dict[str, tuple[str, int, str]] = {
    "QUEUED": ("PENDING", 0, "Queued for indexing..."),
    "EXTRACTING": ("PROCESSING", 12, "Extracting text..."),
    "CHUNKING": ("PROCESSING", 34, "Chunking document..."),
    "EMBEDDING": ("PROCESSING", 72, "Generating embeddings..."),
    "FINALIZING": ("PROCESSING", 90, "Finalizing knowledge index..."),
    "READY": ("READY", 100, "Ready for grounded chat."),
    "FAILED": ("FAILED", 100, "Document processing failed. Re-upload to try again."),
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_ollama_base_url(base_url: str | None) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return DEFAULT_OLLAMA_BASE_URL
    if "://" not in raw:
        raw = f"http://{raw.lstrip('/')}"
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if host in LOCAL_OLLAMA_HOSTS and (port is None or port == 11434):
        return DEFAULT_OLLAMA_BASE_URL
    return raw.rstrip("/")


def _document_progress(stage: str, *, message: str | None = None) -> tuple[str, str, int, str]:
    status, percent, default_message = DOCUMENT_STAGE_STATE[stage]
    return status, stage, percent, message or default_message


def _friendly_processing_message(detail: str | None = None) -> str:
    safe_detail = (detail or "").strip()
    if not safe_detail:
        return DOCUMENT_STAGE_STATE["FAILED"][2]
    lowered = safe_detail.lower()
    if "no usable text" in lowered or "no usable chunk" in lowered:
        return safe_detail
    return DOCUMENT_STAGE_STATE["FAILED"][2]


def _chunk_text(content: str, *, chunk_size: int, chunk_overlap: int) -> list[str]:
    text = content.strip()
    if not text:
        return []
    step = max(1, chunk_size - chunk_overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks


_MARKDOWN_HEADER_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def _split_by_markdown_headers(text: str) -> list[tuple[str, str]]:
    matches = list(_MARKDOWN_HEADER_RE.finditer(text))
    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for index, match in enumerate(matches):
        label = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            sections.append((label, body))
    return sections


def _chunk_text_with_labels(
    content: str,
    *,
    chunk_size: int,
    chunk_overlap: int,
    markdown_aware: bool,
) -> list[tuple[str | None, str]]:
    if not markdown_aware:
        return [(None, chunk) for chunk in _chunk_text(content, chunk_size=chunk_size, chunk_overlap=chunk_overlap)]

    labeled_chunks: list[tuple[str | None, str]] = []
    for label, section_text in _split_by_markdown_headers(content):
        chunks = _chunk_text(section_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not chunks and section_text.strip():
            chunks = [section_text.strip()]
        for chunk in chunks:
            labeled_chunks.append((label or None, chunk))
    return labeled_chunks


class MemoryAssistantStore:
    def __init__(self) -> None:
        self.sessions: set[str] = set()
        self.chats: dict[str, Chat] = {}
        self.messages: dict[str, list[ChatMessage]] = {}
        self.spaces: dict[str, dict[str, Any]] = {}
        self.model_settings = ModelSettings(
            generation=GenerationSettings(
                provider="ollama",
                model=DEFAULT_CHAT_MODEL,
                base_url=DEFAULT_OLLAMA_BASE_URL,
            ),
            embedding=EmbeddingSettings(
                provider="sentence-transformers",
                model=DEFAULT_EMBEDDING_MODEL,
                base_url=None,
            ),
        )
        self.knowledge_settings = KnowledgeSettings()
        self.system_settings = SystemSettings()

    def _ensure_session(self, session_id: str) -> None:
        self.sessions.add(session_id)

    def list_chats(self, session_id: str) -> list[Chat]:
        self._ensure_session(session_id)
        return sorted(
            [chat for chat in self.chats.values() if chat.session_id == session_id],
            key=lambda chat: chat.updated_at,
            reverse=True,
        )

    def create_chat(self, session_id: str) -> Chat:
        self._ensure_session(session_id)
        chat = Chat(
            id=str(uuid4()),
            session_id=session_id,
            title="New chat",
            knowledge_space_id=None,
            created_at=utc_iso(),
            updated_at=utc_iso(),
        )
        self.chats[chat.id] = chat
        self.messages[chat.id] = []
        return chat

    def get_chat(self, session_id: str, chat_id: str) -> Chat:
        chat = self.chats.get(chat_id)
        if chat is None or chat.session_id != session_id:
            raise HTTPException(status_code=404, detail="Chat not found.")
        return chat

    def list_messages(self, session_id: str, chat_id: str) -> list[ChatMessage]:
        _ = self.get_chat(session_id, chat_id)
        return self.messages.get(chat_id, [])

    def rename_chat(self, session_id: str, chat_id: str, title: str) -> Chat:
        chat = self.get_chat(session_id, chat_id)
        chat.title = title.strip() or "New chat"
        chat.updated_at = utc_iso()
        return chat

    def delete_chat(self, session_id: str, chat_id: str) -> None:
        _ = self.get_chat(session_id, chat_id)
        self.chats.pop(chat_id, None)
        self.messages.pop(chat_id, None)

    def list_spaces(self) -> list[dict[str, Any]]:
        return [
            {
                "id": space["space"].id,
                "name": space["space"].name,
                "description": space["space"].description,
                "created_at": space["space"].created_at,
                "documents": [document.model_dump() for document in space["documents"]],
            }
            for space in self.spaces.values()
        ]

    def create_space(self, name: str, description: Optional[str]) -> KnowledgeSpace:
        space = KnowledgeSpace(
            id=str(uuid4()),
            name=name.strip(),
            description=description,
            created_at=utc_iso(),
        )
        self.spaces[space.id] = {"space": space, "documents": [], "chunks": []}
        return space

    def update_space(self, space_id: str, name: str, description: Optional[str]) -> KnowledgeSpace:
        record = self.spaces.get(space_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Knowledge space not found.")
        space = record["space"]
        space.name = name.strip()
        space.description = description
        return space

    def delete_space(self, space_id: str) -> None:
        if self.spaces.pop(space_id, None) is None:
            raise HTTPException(status_code=404, detail="Knowledge space not found.")
        for chat in self.chats.values():
            if chat.knowledge_space_id == space_id:
                chat.knowledge_space_id = None

    def _find_document_record(self, document_id: str) -> tuple[dict[str, Any], KnowledgeDocument] | None:
        for record in self.spaces.values():
            for document in record["documents"]:
                if document.id == document_id:
                    return record, document
        return None

    def _set_document_stage(self, document_id: str, stage: str, *, message: str | None = None) -> KnowledgeDocument:
        found = self._find_document_record(document_id)
        if found is None:
            raise HTTPException(status_code=404, detail="Knowledge document not found.")
        _, document = found
        status, _, percent, resolved_message = _document_progress(stage, message=message)
        document.processing_status = status
        document.processing_stage = stage
        document.processing_progress_percent = percent
        document.processing_message = resolved_message
        return document

    def queue_document(
        self,
        space_id: str,
        *,
        filename: str | None,
        content_type: str | None,
        raw: bytes,
    ) -> KnowledgeDocument:
        record = self.spaces.get(space_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Knowledge space not found.")
        text = raw.decode("utf-8", errors="ignore").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Uploaded file produced no usable text.")

        status, stage, percent, progress_message = _document_progress("QUEUED")
        document = KnowledgeDocument(
            id=str(uuid4()),
            space_id=space_id,
            filename=filename or "document.txt",
            content_type=content_type or "application/octet-stream",
            processing_status=status,
            processing_stage=stage,
            processing_progress_percent=percent,
            processing_message=progress_message,
            content=text,
            chunk_count=0,
            created_at=utc_iso(),
        )
        record["documents"].insert(0, document)
        return document

    def process_document(self, document_id: str) -> None:
        found = self._find_document_record(document_id)
        if found is None:
            return
        record, document = found
        try:
            self._set_document_stage(document_id, "EXTRACTING")
            content = document.content.strip()
            if not content:
                raise ValueError("Uploaded file produced no usable text.")

            self._set_document_stage(document_id, "CHUNKING")
            labeled_chunks = _chunk_text_with_labels(
                content,
                chunk_size=self.knowledge_settings.chunk_size,
                chunk_overlap=self.knowledge_settings.chunk_overlap,
                markdown_aware=self.knowledge_settings.enable_markdown_chunking,
            )
            if not labeled_chunks:
                raise ValueError("Uploaded file produced no usable chunks.")

            self._set_document_stage(document_id, "EMBEDDING")
            self._set_document_stage(document_id, "FINALIZING")
            record["chunks"] = [chunk for chunk in record["chunks"] if chunk["document_id"] != document_id]
            record["chunks"].extend(
                {
                    "id": str(uuid4()),
                    "document_id": document_id,
                    "text": chunk_text,
                    "section_label": section_label,
                }
                for section_label, chunk_text in labeled_chunks
            )
            self._set_document_stage(document_id, "READY")
            document.chunk_count = len(labeled_chunks)
        except Exception as exc:
            failure_message = _friendly_processing_message(str(exc))
            self._set_document_stage(document_id, "FAILED", message=failure_message)
            document.chunk_count = 0

    def select_space(self, session_id: str, chat_id: str, space_id: str) -> Chat:
        chat = self.get_chat(session_id, chat_id)
        if space_id not in self.spaces:
            raise HTTPException(status_code=404, detail="Knowledge space not found.")
        chat.knowledge_space_id = space_id
        chat.updated_at = utc_iso()
        return chat

    def clear_selection(self, session_id: str, chat_id: str) -> Chat:
        chat = self.get_chat(session_id, chat_id)
        chat.knowledge_space_id = None
        chat.updated_at = utc_iso()
        return chat

    def _retrieve(self, space_id: str, message: str) -> list[Citation]:
        record = self.spaces.get(space_id)
        if record is None:
            return []
        keywords = {token.lower() for token in message.split() if len(token) > 2}
        citations: list[Citation] = []
        for index, chunk in enumerate(record["chunks"], start=1):
            chunk_text = chunk["text"]
            if keywords and not any(keyword in chunk_text.lower() for keyword in keywords):
                continue
            document = next(
                doc for doc in record["documents"] if doc.id == chunk["document_id"]
            )
            citations.append(
                Citation(
                    id=str(index),
                    title=document.filename,
                    excerpt=chunk_text[:240],
                    section=chunk.get("section_label"),
                )
            )
            if len(citations) >= self.knowledge_settings.retrieval_top_k:
                break
        return citations

    def _stream_stub_events(self, *, reply: str, grounded: bool) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = [{"type": "grounded", "value": grounded}]
        if self.system_settings.show_thinking_overlay:
            events.append({"type": "thinking", "value": True})
            events.append({"type": "thinking_text", "text": "Checking selected knowledge space."})
            events.append({"type": "thinking", "value": False})
        events.extend({"type": "token", "token": f"{token} "} for token in reply.split())
        return events

    def append_user_message(self, session_id: str, chat_id: str, content: str) -> ChatMessage:
        chat = self.get_chat(session_id, chat_id)
        if chat.title == "New chat":
            chat.title = content.strip()[:60] or "New chat"
        chat.updated_at = utc_iso()
        message = ChatMessage(
            id=str(uuid4()),
            role="USER",
            content=content,
            grounded=False,
            citations=[],
            feedback_vote=None,
            created_at=utc_iso(),
        )
        self.messages.setdefault(chat_id, []).append(message)
        return message

    def append_assistant_message(self, session_id: str, chat_id: str, content: str) -> ChatMessage:
        chat = self.get_chat(session_id, chat_id)
        citations = self._retrieve(chat.knowledge_space_id, content) if chat.knowledge_space_id else []
        grounded = len(citations) > 0
        if grounded:
            reply = (
                f"According to {citations[0].title}, {citations[0].excerpt}"
                if citations
                else f"Assistant response to: {content}"
            )
        else:
            reply = f"Assistant response to: {content}"
        message = ChatMessage(
            id=str(uuid4()),
            role="ASSISTANT",
            content=reply,
            grounded=grounded,
            citations=citations,
            feedback_vote=None,
            created_at=utc_iso(),
        )
        chat.updated_at = utc_iso()
        self.messages.setdefault(chat_id, []).append(message)
        return message

    def stream_assistant_reply(self, session_id: str, chat_id: str, content: str):
        assistant_message = self.append_assistant_message(session_id, chat_id, content)
        for event in self._stream_stub_events(reply=assistant_message.content, grounded=assistant_message.grounded):
            yield event
        yield {"type": "message", "message": assistant_message.model_dump()}
        if assistant_message.citations:
            yield {
                "type": "sources",
                "chunks": [citation.model_dump() for citation in assistant_message.citations],
            }

    def regenerate(self, session_id: str, chat_id: str) -> ChatMessage:
        history = self.list_messages(session_id, chat_id)
        last_user = next((message for message in reversed(history) if message.role == "USER"), None)
        if last_user is None:
            raise HTTPException(status_code=400, detail="No user message to regenerate from.")
        return self.append_assistant_message(session_id, chat_id, last_user.content)

    def stream_regenerated_reply(self, session_id: str, chat_id: str):
        history = self.list_messages(session_id, chat_id)
        last_user = next((message for message in reversed(history) if message.role == "USER"), None)
        if last_user is None:
            raise HTTPException(status_code=400, detail="No user message to regenerate from.")
        yield from self.stream_assistant_reply(session_id, chat_id, last_user.content)

    def set_message_feedback(self, session_id: str, message_id: str, vote: Optional[FeedbackVote]) -> ChatMessage:
        for chat in self.list_chats(session_id):
            chat_messages = self.messages.get(chat.id, [])
            for index, message in enumerate(chat_messages):
                if message.id != message_id:
                    continue
                if message.role != "ASSISTANT":
                    raise HTTPException(status_code=400, detail="Only assistant messages can be rated.")
                updated = message.model_copy(update={"feedback_vote": vote})
                chat_messages[index] = updated
                return updated
        raise HTTPException(status_code=404, detail="Message not found.")

    def get_model_settings(self) -> ModelSettings:
        return self.model_settings

    def set_model_settings(self, value: ModelSettings) -> ModelSettings:
        self.model_settings = value
        return self.model_settings

    def get_knowledge_settings(self) -> KnowledgeSettings:
        return self.knowledge_settings

    def set_knowledge_settings(self, value: KnowledgeSettings) -> KnowledgeSettings:
        self.knowledge_settings = value
        return self.knowledge_settings

    def get_system_settings(self) -> SystemSettings:
        return self.system_settings

    def set_system_settings(self, value: SystemSettings) -> SystemSettings:
        self.system_settings = value
        return self.system_settings

    def get_ollama_models(self, base_url: Optional[str] = None) -> list[dict[str, Any]]:
        default_models = []
        if self.model_settings.generation.provider == "ollama":
            default_models.append({"name": self.model_settings.generation.model})
        if self.model_settings.embedding.provider == "ollama":
            default_models.append({"name": self.model_settings.embedding.model})
        if not default_models:
            default_models.append({"name": DEFAULT_CHAT_MODEL})
        unique: dict[str, dict[str, Any]] = {}
        for item in default_models:
            unique[item["name"]] = item
        return list(unique.values())

    def get_ollama_health(self, base_url: Optional[str] = None) -> dict[str, Any]:
        models = self.get_ollama_models(base_url)
        return {"ok": True, "model_count": len(models)}

    def get_openrouter_models(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> list[dict[str, Any]]:
        if not api_key:
            return [
                ProviderModelOption(
                    id=OPENROUTER_DEFAULT_MODEL,
                    label=f"{OPENROUTER_DEFAULT_MODEL} (default)",
                    supports_reasoning=True,
                ).model_dump()
            ]
        models = list_openrouter_models(api_key=api_key, base_url=base_url)
        return [
            ProviderModelOption(
                id=str(item.get("id") or item.get("name") or ""),
                label=str(item.get("name") or item.get("id") or ""),
                supports_reasoning=bool(
                    isinstance(item.get("supported_parameters"), list)
                    and (
                        "reasoning" in item["supported_parameters"]
                        or "include_reasoning" in item["supported_parameters"]
                    )
                ),
            ).model_dump()
            for item in models
            if str(item.get("id") or item.get("name") or "").strip()
        ]

    def pull_ollama_model(self, model: str, base_url: Optional[str] = None):
        target = model.strip()
        if not target:
            raise HTTPException(status_code=400, detail="Model is required.")
        yield json.dumps({"status": "success", "completed": 1, "total": 1, "model": target})


class PostgresAssistantStore:
    def __init__(self) -> None:
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is required for the postgres assistant store.")
        self._database_url = DEFAULT_DATABASE_URL
        self._default_ollama_base_url = DEFAULT_OLLAMA_BASE_URL
        self._init_schema()

    def _connect(self):
        return psycopg2.connect(self._database_url)

    def _init_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS assistant_sessions (
                  id TEXT PRIMARY KEY,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS model_settings (
                  id SMALLINT PRIMARY KEY DEFAULT 1,
                  provider TEXT NOT NULL,
                  model TEXT NOT NULL,
                  embedding_model TEXT NOT NULL
                );

                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS generation_api_key TEXT;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS generation_base_url TEXT;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS system_prompt TEXT;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS temperature DOUBLE PRECISION;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS max_tokens INTEGER;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS context_max_tokens INTEGER;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS auto_compress BOOLEAN;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS embedding_provider TEXT;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS embedding_api_key TEXT;
                ALTER TABLE model_settings ADD COLUMN IF NOT EXISTS embedding_base_url TEXT;

                CREATE TABLE IF NOT EXISTS knowledge_settings (
                  id SMALLINT PRIMARY KEY DEFAULT 1,
                  chunk_size INTEGER NOT NULL,
                  chunk_overlap INTEGER NOT NULL,
                  retrieval_top_k INTEGER NOT NULL,
                  relevance_threshold DOUBLE PRECISION NOT NULL,
                  enable_markdown_chunking BOOLEAN NOT NULL DEFAULT TRUE,
                  query_augmentation BOOLEAN NOT NULL DEFAULT FALSE,
                  hybrid_search_enabled BOOLEAN NOT NULL,
                  hybrid_bm25_weight DOUBLE PRECISION NOT NULL DEFAULT 0.5,
                  rag_template TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS system_settings (
                  id SMALLINT PRIMARY KEY DEFAULT 1,
                  app_name TEXT NOT NULL,
                  theme TEXT NOT NULL,
                  show_thinking_overlay BOOLEAN NOT NULL DEFAULT TRUE
                );

                CREATE TABLE IF NOT EXISTS knowledge_spaces (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  description TEXT,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                CREATE TABLE IF NOT EXISTS knowledge_documents (
                  id TEXT PRIMARY KEY,
                  space_id TEXT NOT NULL REFERENCES knowledge_spaces(id) ON DELETE CASCADE,
                  filename TEXT NOT NULL,
                  content_type TEXT NOT NULL,
                  processing_status TEXT NOT NULL,
                  processing_stage TEXT NOT NULL DEFAULT 'QUEUED',
                  processing_progress_percent INTEGER NOT NULL DEFAULT 0,
                  processing_message TEXT,
                  content TEXT NOT NULL,
                  chunk_count INTEGER NOT NULL DEFAULT 0,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedding_provider TEXT;
                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedding_model TEXT;
                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER;
                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS processing_stage TEXT NOT NULL DEFAULT 'QUEUED';
                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS processing_progress_percent INTEGER NOT NULL DEFAULT 0;
                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS processing_message TEXT;

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                  id TEXT PRIMARY KEY,
                  document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                  space_id TEXT NOT NULL REFERENCES knowledge_spaces(id) ON DELETE CASCADE,
                  chunk_text TEXT NOT NULL,
                  section_label TEXT,
                  embedding vector,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER;

                CREATE TABLE IF NOT EXISTS assistant_chats (
                  id TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES assistant_sessions(id) ON DELETE CASCADE,
                  title TEXT NOT NULL,
                  knowledge_space_id TEXT REFERENCES knowledge_spaces(id) ON DELETE SET NULL,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  deleted_at TIMESTAMPTZ
                );

                CREATE TABLE IF NOT EXISTS assistant_chat_messages (
                  id TEXT PRIMARY KEY,
                  chat_id TEXT NOT NULL REFERENCES assistant_chats(id) ON DELETE CASCADE,
                  role TEXT NOT NULL,
                  content TEXT NOT NULL,
                  grounded BOOLEAN NOT NULL DEFAULT FALSE,
                  citations JSONB NOT NULL DEFAULT '[]'::jsonb,
                  feedback_vote TEXT,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_space_id ON knowledge_chunks(space_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding_dimension ON knowledge_chunks(embedding_dimension);
                CREATE INDEX IF NOT EXISTS idx_documents_space_id ON knowledge_documents(space_id);
                CREATE INDEX IF NOT EXISTS idx_chats_session_id ON assistant_chats(session_id);
                """
            )
            cur.execute(
                """
                ALTER TABLE assistant_chat_messages
                ADD COLUMN IF NOT EXISTS feedback_vote TEXT;
                """
            )
            cur.execute(
                """
                INSERT INTO model_settings (
                  id, provider, model, embedding_provider, embedding_model,
                  generation_api_key, generation_base_url, system_prompt,
                  temperature, max_tokens, context_max_tokens, auto_compress,
                  embedding_api_key, embedding_base_url
                )
                VALUES (
                  1, 'ollama', %s, 'sentence-transformers', %s,
                  NULL, %s, 'You are a helpful AI assistant.',
                  0.7, 1024, 8192, FALSE,
                  NULL, NULL
                )
                ON CONFLICT (id) DO NOTHING;
                """,
                (DEFAULT_CHAT_MODEL, DEFAULT_EMBEDDING_MODEL, DEFAULT_OLLAMA_BASE_URL),
            )
            cur.execute(
                """
                UPDATE model_settings
                SET embedding_provider = COALESCE(embedding_provider, 'sentence-transformers'),
                    generation_base_url = COALESCE(generation_base_url, %s),
                    embedding_base_url = CASE
                      WHEN embedding_provider = 'sentence-transformers' THEN NULL
                      ELSE COALESCE(embedding_base_url, %s)
                    END,
                    system_prompt = COALESCE(system_prompt, 'You are a helpful AI assistant.'),
                    temperature = COALESCE(temperature, 0.7),
                    max_tokens = COALESCE(max_tokens, 1024),
                    context_max_tokens = COALESCE(context_max_tokens, 8192),
                    auto_compress = COALESCE(auto_compress, FALSE)
                WHERE id = 1;
                """,
                (DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_BASE_URL),
            )
            cur.execute(
                """
                UPDATE model_settings
                SET embedding_provider = 'sentence-transformers',
                    embedding_model = %s,
                    embedding_base_url = NULL
                WHERE id = 1
                  AND embedding_provider = 'ollama'
                  AND embedding_model = 'nomic-embed-text';
                """,
                (DEFAULT_EMBEDDING_MODEL,),
            )
            cur.execute(
                """
                UPDATE model_settings
                SET generation_base_url = %s
                WHERE id = 1
                  AND provider = 'ollama'
                  AND generation_base_url IN (
                    'http://ollama:11434',
                    'https://ollama:11434',
                    'http://host.docker.internal:11434',
                    'https://host.docker.internal:11434',
                    'http://127.0.0.1:11434',
                    'https://127.0.0.1:11434'
                  );
                """,
                (DEFAULT_OLLAMA_BASE_URL,),
            )
            cur.execute(
                """
                UPDATE model_settings
                SET embedding_base_url = %s
                WHERE id = 1
                  AND embedding_provider = 'ollama'
                  AND embedding_base_url IN (
                    'http://ollama:11434',
                    'https://ollama:11434',
                    'http://host.docker.internal:11434',
                    'https://host.docker.internal:11434',
                    'http://127.0.0.1:11434',
                    'https://127.0.0.1:11434'
                  );
                """,
                (DEFAULT_OLLAMA_BASE_URL,),
            )
            cur.execute(
                """
                INSERT INTO knowledge_settings (
                  id, chunk_size, chunk_overlap, retrieval_top_k, relevance_threshold,
                  enable_markdown_chunking, query_augmentation, hybrid_search_enabled,
                  hybrid_bm25_weight, rag_template
                )
                VALUES (
                  1, 1000, 120, 5, 0.0, TRUE, FALSE, FALSE, 0.5,
                  'Use the provided context when it is relevant. If the context is insufficient, answer honestly and say what is missing.'
                )
                ON CONFLICT (id) DO NOTHING;
                """
            )
            cur.execute(
                """
                ALTER TABLE knowledge_settings
                ADD COLUMN IF NOT EXISTS enable_markdown_chunking BOOLEAN NOT NULL DEFAULT TRUE;
                """
            )
            cur.execute(
                """
                ALTER TABLE knowledge_settings
                ADD COLUMN IF NOT EXISTS query_augmentation BOOLEAN NOT NULL DEFAULT FALSE;
                """
            )
            cur.execute(
                """
                ALTER TABLE knowledge_settings
                ADD COLUMN IF NOT EXISTS hybrid_bm25_weight DOUBLE PRECISION NOT NULL DEFAULT 0.5;
                """
            )
            cur.execute(
                """
                ALTER TABLE knowledge_chunks
                ADD COLUMN IF NOT EXISTS section_label TEXT;
                """
            )
            cur.execute(
                """
                UPDATE knowledge_documents
                SET processing_stage = CASE
                      WHEN processing_status = 'READY' THEN 'READY'
                      WHEN processing_status = 'FAILED' THEN 'FAILED'
                      WHEN processing_status = 'PROCESSING' THEN 'FINALIZING'
                      ELSE 'QUEUED'
                    END,
                    processing_progress_percent = CASE
                      WHEN processing_status = 'READY' THEN 100
                      WHEN processing_status = 'FAILED' THEN GREATEST(processing_progress_percent, 5)
                      WHEN processing_status = 'PROCESSING' THEN GREATEST(processing_progress_percent, 90)
                      ELSE processing_progress_percent
                    END,
                    processing_message = CASE
                      WHEN processing_status = 'READY' THEN COALESCE(processing_message, 'Ready for grounded chat.')
                      WHEN processing_status = 'FAILED' THEN COALESCE(processing_message, 'Document processing failed. Re-upload to try again.')
                      WHEN processing_status = 'PROCESSING' THEN COALESCE(processing_message, 'Finalizing knowledge index...')
                      ELSE COALESCE(processing_message, 'Queued for indexing...')
                    END;
                """
            )
            cur.execute(
                """
                INSERT INTO system_settings (id, app_name, theme)
                VALUES (1, 'Assistant', 'light')
                ON CONFLICT (id) DO NOTHING;
                """
            )
            cur.execute(
                """
                ALTER TABLE system_settings
                ADD COLUMN IF NOT EXISTS show_thinking_overlay BOOLEAN NOT NULL DEFAULT TRUE;
                """
            )
            cur.execute(
                """
                UPDATE system_settings
                SET show_thinking_overlay = COALESCE(show_thinking_overlay, TRUE)
                WHERE id = 1;
                """
            )

    def _ensure_session(self, session_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO assistant_sessions (id)
                VALUES (%s)
                ON CONFLICT (id) DO NOTHING;
                """,
                (session_id,),
            )

    def _row_to_chat(self, row: dict[str, Any]) -> Chat:
        return Chat(
            id=row["id"],
            session_id=row["session_id"],
            title=row["title"],
            knowledge_space_id=row["knowledge_space_id"],
            created_at=to_iso(row["created_at"]),
            updated_at=to_iso(row["updated_at"]),
        )

    def _row_to_document(self, row: dict[str, Any]) -> KnowledgeDocument:
        return KnowledgeDocument(
            id=row["id"],
            space_id=row["space_id"],
            filename=row["filename"],
            content_type=row["content_type"],
            processing_status=row["processing_status"],
            processing_stage=row["processing_stage"],
            processing_progress_percent=int(row["processing_progress_percent"] or 0),
            processing_message=row.get("processing_message"),
            content=row["content"],
            chunk_count=row["chunk_count"],
            created_at=to_iso(row["created_at"]),
        )

    def _row_to_message(self, row: dict[str, Any]) -> ChatMessage:
        citations = [Citation(**item) for item in (row.get("citations") or [])]
        return ChatMessage(
            id=row["id"],
            role=row["role"],
            content=row["content"],
            grounded=row["grounded"],
            citations=citations,
            feedback_vote=row.get("feedback_vote"),
            created_at=to_iso(row["created_at"]),
        )

    def get_model_settings(self) -> ModelSettings:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  provider, model, generation_api_key, generation_base_url, system_prompt,
                  temperature, max_tokens, context_max_tokens, auto_compress,
                  embedding_provider, embedding_model, embedding_api_key, embedding_base_url
                FROM model_settings
                WHERE id = 1;
                """
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Model settings are missing.")
            generation_base_url = (
                _canonical_ollama_base_url(row["generation_base_url"])
                if row["provider"] == "ollama"
                else row["generation_base_url"]
            )
            embedding_base_url = (
                _canonical_ollama_base_url(row["embedding_base_url"])
                if row["embedding_provider"] == "ollama"
                else row["embedding_base_url"]
            )
            return ModelSettings(
                generation=GenerationSettings(
                    provider=row["provider"],
                    model=row["model"],
                    api_key_set=bool(row["generation_api_key"]),
                    base_url=generation_base_url,
                    system_prompt=row["system_prompt"],
                    temperature=float(row["temperature"]),
                    max_tokens=row["max_tokens"],
                    context_max_tokens=row["context_max_tokens"],
                    auto_compress=bool(row["auto_compress"]),
                ),
                embedding=EmbeddingSettings(
                    provider=row["embedding_provider"],
                    model=row["embedding_model"],
                    api_key_set=bool(row["embedding_api_key"]),
                    base_url=embedding_base_url,
                ),
            )

    def set_model_settings(self, value: ModelSettings, *, generation_api_key: str | None, embedding_api_key: str | None) -> ModelSettings:
        generation_base_url = (
            _canonical_ollama_base_url(value.generation.base_url)
            if value.generation.provider == "ollama"
            else value.generation.base_url
        )
        embedding_base_url = (
            _canonical_ollama_base_url(value.embedding.base_url)
            if value.embedding.provider == "ollama"
            else value.embedding.base_url
        )
        with self._connect() as conn, conn.cursor() as cur:
            if generation_api_key:
                cur.execute(
                    """
                    UPDATE model_settings
                    SET provider = %s,
                        model = %s,
                        generation_api_key = %s,
                        generation_base_url = %s,
                        system_prompt = %s,
                        temperature = %s,
                        max_tokens = %s,
                        context_max_tokens = %s,
                        auto_compress = %s,
                        embedding_provider = %s,
                        embedding_model = %s,
                        embedding_api_key = COALESCE(%s, embedding_api_key),
                        embedding_base_url = %s
                    WHERE id = 1;
                    """,
                    (
                        value.generation.provider,
                        value.generation.model,
                        generation_api_key,
                        generation_base_url,
                        value.generation.system_prompt,
                        value.generation.temperature,
                        value.generation.max_tokens,
                        value.generation.context_max_tokens,
                        value.generation.auto_compress,
                        value.embedding.provider,
                        value.embedding.model,
                        embedding_api_key,
                        embedding_base_url,
                    ),
                )
            else:
                cur.execute(
                    """
                    UPDATE model_settings
                    SET provider = %s,
                        model = %s,
                        generation_base_url = %s,
                        system_prompt = %s,
                        temperature = %s,
                        max_tokens = %s,
                        context_max_tokens = %s,
                        auto_compress = %s,
                        embedding_provider = %s,
                        embedding_model = %s,
                        embedding_api_key = COALESCE(%s, embedding_api_key),
                        embedding_base_url = %s
                    WHERE id = 1;
                    """,
                    (
                        value.generation.provider,
                        value.generation.model,
                        generation_base_url,
                        value.generation.system_prompt,
                        value.generation.temperature,
                        value.generation.max_tokens,
                        value.generation.context_max_tokens,
                        value.generation.auto_compress,
                        value.embedding.provider,
                        value.embedding.model,
                        embedding_api_key,
                        embedding_base_url,
                    ),
                )
                if generation_api_key == "":
                    cur.execute(
                        """
                        UPDATE model_settings SET generation_api_key = NULL WHERE id = 1;
                        """
                    )
            if generation_api_key == "":
                cur.execute("UPDATE model_settings SET generation_api_key = NULL WHERE id = 1;")
            if embedding_api_key == "":
                cur.execute("UPDATE model_settings SET embedding_api_key = NULL WHERE id = 1;")
            if generation_api_key and generation_api_key.strip():
                cur.execute(
                    "UPDATE model_settings SET generation_api_key = %s WHERE id = 1;",
                    (generation_api_key.strip(),),
                )
            if embedding_api_key and embedding_api_key.strip():
                cur.execute(
                    "UPDATE model_settings SET embedding_api_key = %s WHERE id = 1;",
                    (embedding_api_key.strip(),),
                )
        return self.get_model_settings()

    def get_knowledge_settings(self) -> KnowledgeSettings:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT chunk_size, chunk_overlap, retrieval_top_k, relevance_threshold,
                       enable_markdown_chunking, query_augmentation, hybrid_search_enabled,
                       hybrid_bm25_weight, rag_template
                FROM knowledge_settings
                WHERE id = 1;
                """
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Knowledge settings are missing.")
            return KnowledgeSettings(**row)

    def set_knowledge_settings(self, value: KnowledgeSettings) -> KnowledgeSettings:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE knowledge_settings
                SET chunk_size = %s,
                    chunk_overlap = %s,
                    retrieval_top_k = %s,
                    relevance_threshold = %s,
                    enable_markdown_chunking = %s,
                    query_augmentation = %s,
                    hybrid_search_enabled = %s,
                    hybrid_bm25_weight = %s,
                    rag_template = %s
                WHERE id = 1;
                """,
                (
                    value.chunk_size,
                    value.chunk_overlap,
                    value.retrieval_top_k,
                    value.relevance_threshold,
                    value.enable_markdown_chunking,
                    value.query_augmentation,
                    value.hybrid_search_enabled,
                    value.hybrid_bm25_weight,
                    value.rag_template,
                ),
            )
        return self.get_knowledge_settings()

    def get_system_settings(self) -> SystemSettings:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT app_name, theme, show_thinking_overlay FROM system_settings WHERE id = 1;")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="System settings are missing.")
            return SystemSettings(**row)

    def set_system_settings(self, value: SystemSettings) -> SystemSettings:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE system_settings
                SET app_name = %s, theme = %s, show_thinking_overlay = %s
                WHERE id = 1;
                """,
                (value.app_name, value.theme, value.show_thinking_overlay),
            )
        return self.get_system_settings()

    def _generation_row(self) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT provider, model, generation_api_key, generation_base_url, system_prompt,
                       temperature, max_tokens, context_max_tokens, auto_compress
                FROM model_settings
                WHERE id = 1;
                """
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Generation provider is not configured.")
            result = dict(row)
            if result["provider"] == "ollama":
                result["generation_base_url"] = _canonical_ollama_base_url(result["generation_base_url"])
            return result

    def _embedding_row(self) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT embedding_provider, embedding_model, embedding_api_key, embedding_base_url
                FROM model_settings
                WHERE id = 1;
                """
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Embedding provider is not configured.")
            result = dict(row)
            if result["embedding_provider"] == "ollama":
                result["embedding_base_url"] = _canonical_ollama_base_url(result["embedding_base_url"])
            return result

    def _show_thinking_overlay(self) -> bool:
        return bool(self.get_system_settings().show_thinking_overlay)

    def _embed_text(self, text: str) -> list[float]:
        row = self._embedding_row()
        provider = build_embedding_provider(
            row["embedding_provider"],
            model_name=row["embedding_model"],
            api_key=row["embedding_api_key"],
            base_url=row["embedding_base_url"] or self._default_ollama_base_url,
        )
        return provider.embed_one(text)

    def _augment_query(self, query: str) -> str:
        settings = self.get_knowledge_settings()
        if not settings.query_augmentation:
            return query
        try:
            row = self._generation_row()
            provider = build_generation_provider(
                row["provider"],
                model_name=row["model"],
                api_key=row["generation_api_key"],
                base_url=row["generation_base_url"] or self._default_ollama_base_url,
            )
            rewritten = provider.generate(
                system_prompt=(
                    "Rewrite the user question as a concise document retrieval query. "
                    "Return only the rewritten query."
                ),
                messages=[{"role": "user", "content": query}],
                max_tokens=64,
                temperature=0.1,
            )
            return rewritten or query
        except Exception:
            return query

    def _generate_answer(self, *, prompt: str, context: str, citations: list[Citation], history: list[ChatMessage]) -> str:
        row = self._generation_row()
        citation_guide = "\n".join(f"[{citation.id}] {citation.title}: {citation.excerpt}" for citation in citations)
        rag_prompt = self.get_knowledge_settings().rag_template
        system_prompt = row["system_prompt"] or "You are a helpful AI assistant."
        if rag_prompt:
            system_prompt = f"{system_prompt}\n\n{rag_prompt}"
        if citations:
            system_prompt = (
                f"{system_prompt}\n\n"
                "Use retrieved context only when it is directly relevant and sufficient. "
                "If the context is weak or insufficient, answer normally without citing it. "
                "Only use citation markers like [1] when the answer is supported by the retrieved context."
            )

        conversation: list[dict[str, str]] = []
        assistant_role = "model" if row["provider"] == "google" else "assistant"
        recent_history = history[-8:]
        for message in recent_history[:-1]:
            conversation.append(
                {
                    "role": assistant_role if message.role == "ASSISTANT" else "user",
                    "content": message.content,
                }
            )
        conversation.append(
            {
                "role": "user",
                "content": prompt,
            }
        )
        if citations:
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        "Relevant course material follows. Use it only if it genuinely supports the answer.\n\n"
                        f"Retrieved context:\n{context}\n\n"
                        f"Available citations:\n{citation_guide or 'None'}"
                    ),
                }
            )

        provider = build_generation_provider(
            row["provider"],
            model_name=row["model"],
            api_key=row["generation_api_key"],
            base_url=row["generation_base_url"] or self._default_ollama_base_url,
        )
        reply = provider.generate(
            system_prompt=system_prompt,
            messages=conversation,
            max_tokens=row["max_tokens"],
            temperature=float(row["temperature"]),
        )
        if not reply.strip():
            raise HTTPException(status_code=503, detail="Model returned no content.")
        return reply

    def _build_generation_events(
        self,
        *,
        prompt: str,
        history: list[ChatMessage],
        citations: list[Citation],
    ):
        row = self._generation_row()
        rag_prompt = self.get_knowledge_settings().rag_template
        system_prompt = row["system_prompt"] or "You are a helpful AI assistant."
        if rag_prompt:
            system_prompt = f"{system_prompt}\n\n{rag_prompt}"
        if citations:
            system_prompt = (
                f"{system_prompt}\n\n"
                "Use retrieved context only when it is directly relevant and sufficient. "
                "If the context is weak or insufficient, answer normally without citing it. "
                "Only use citation markers like [1] when the answer is supported by the retrieved context."
            )

        conversation: list[dict[str, str]] = []
        assistant_role = "model" if row["provider"] == "google" else "assistant"
        recent_history = history[-8:]
        for message in recent_history[:-1]:
            conversation.append(
                {
                    "role": assistant_role if message.role == "ASSISTANT" else "user",
                    "content": message.content,
                }
            )
        conversation.append({"role": "user", "content": prompt})
        if citations:
            citation_guide = "\n".join(
                f"[{citation.id}] {citation.title}: {citation.excerpt}" for citation in citations
            )
            context = "\n\n".join(f"[{citation.id}] {citation.excerpt}" for citation in citations)
            conversation.append(
                {
                    "role": "user",
                    "content": (
                        "Relevant course material follows. Use it only if it genuinely supports the answer.\n\n"
                        f"Retrieved context:\n{context}\n\n"
                        f"Available citations:\n{citation_guide or 'None'}"
                    ),
                }
            )

        provider = build_generation_provider(
            row["provider"],
            model_name=row["model"],
            api_key=row["generation_api_key"],
            base_url=row["generation_base_url"] or self._default_ollama_base_url,
        )
        yield from provider.stream_events(
            system_prompt=system_prompt,
            messages=conversation,
            max_tokens=row["max_tokens"],
            temperature=float(row["temperature"]),
        )

    def list_chats(self, session_id: str) -> list[Chat]:
        self._ensure_session(session_id)
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, session_id, title, knowledge_space_id, created_at, updated_at
                FROM assistant_chats
                WHERE session_id = %s AND deleted_at IS NULL
                ORDER BY updated_at DESC;
                """,
                (session_id,),
            )
            return [self._row_to_chat(row) for row in cur.fetchall()]

    def create_chat(self, session_id: str) -> Chat:
        self._ensure_session(session_id)
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            chat_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO assistant_chats (id, session_id, title)
                VALUES (%s, %s, %s)
                RETURNING id, session_id, title, knowledge_space_id, created_at, updated_at;
                """,
                (chat_id, session_id, "New chat"),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Failed to create chat.")
            return self._row_to_chat(row)

    def get_chat(self, session_id: str, chat_id: str) -> Chat:
        self._ensure_session(session_id)
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, session_id, title, knowledge_space_id, created_at, updated_at
                FROM assistant_chats
                WHERE id = %s AND session_id = %s AND deleted_at IS NULL;
                """,
                (chat_id, session_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Chat not found.")
            return self._row_to_chat(row)

    def list_messages(self, session_id: str, chat_id: str) -> list[ChatMessage]:
        _ = self.get_chat(session_id, chat_id)
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, role, content, grounded, citations, feedback_vote, created_at
                FROM assistant_chat_messages
                WHERE chat_id = %s
                ORDER BY created_at ASC;
                """,
                (chat_id,),
            )
            return [self._row_to_message(row) for row in cur.fetchall()]

    def rename_chat(self, session_id: str, chat_id: str, title: str) -> Chat:
        _ = self.get_chat(session_id, chat_id)
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE assistant_chats
                SET title = %s, updated_at = now()
                WHERE id = %s AND session_id = %s
                RETURNING id, session_id, title, knowledge_space_id, created_at, updated_at;
                """,
                (title.strip() or "New chat", chat_id, session_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Chat not found.")
            return self._row_to_chat(row)

    def delete_chat(self, session_id: str, chat_id: str) -> None:
        _ = self.get_chat(session_id, chat_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE assistant_chats
                SET deleted_at = now(), updated_at = now()
                WHERE id = %s AND session_id = %s;
                """,
                (chat_id, session_id),
            )

    def list_spaces(self) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, name, description, created_at
                FROM knowledge_spaces
                ORDER BY created_at ASC;
                """
            )
            spaces = cur.fetchall()
            cur.execute(
                """
                SELECT
                  id,
                  space_id,
                  filename,
                  content_type,
                  processing_status,
                  processing_stage,
                  processing_progress_percent,
                  processing_message,
                  content,
                  chunk_count,
                  created_at
                FROM knowledge_documents
                ORDER BY created_at DESC;
                """
            )
            documents = cur.fetchall()

        by_space: dict[str, list[dict[str, Any]]] = {}
        for row in documents:
            by_space.setdefault(row["space_id"], []).append(self._row_to_document(row).model_dump())

        return [
            {
                "id": space["id"],
                "name": space["name"],
                "description": space["description"],
                "created_at": to_iso(space["created_at"]),
                "documents": by_space.get(space["id"], []),
            }
            for space in spaces
        ]

    def create_space(self, name: str, description: Optional[str]) -> KnowledgeSpace:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            space_id = str(uuid4())
            cur.execute(
                """
                INSERT INTO knowledge_spaces (id, name, description)
                VALUES (%s, %s, %s)
                RETURNING id, name, description, created_at;
                """,
                (space_id, name.strip(), description),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Failed to create knowledge space.")
            return KnowledgeSpace(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                created_at=to_iso(row["created_at"]),
            )

    def update_space(self, space_id: str, name: str, description: Optional[str]) -> KnowledgeSpace:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE knowledge_spaces
                SET name = %s, description = %s
                WHERE id = %s
                RETURNING id, name, description, created_at;
                """,
                (name.strip(), description, space_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Knowledge space not found.")
            return KnowledgeSpace(
                id=row["id"],
                name=row["name"],
                description=row["description"],
                created_at=to_iso(row["created_at"]),
            )

    def delete_space(self, space_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_spaces WHERE id = %s;", (space_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Knowledge space not found.")

    def _get_document_row(self, document_id: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  id,
                  space_id,
                  filename,
                  content_type,
                  processing_status,
                  processing_stage,
                  processing_progress_percent,
                  processing_message,
                  content,
                  chunk_count,
                  embedding_provider,
                  embedding_model,
                  embedding_dimension,
                  created_at
                FROM knowledge_documents
                WHERE id = %s;
                """,
                (document_id,),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def _update_document_progress(self, document_id: str, stage: str, *, message: str | None = None) -> None:
        status, _, percent, resolved_message = _document_progress(stage, message=message)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE knowledge_documents
                SET processing_status = %s,
                    processing_stage = %s,
                    processing_progress_percent = %s,
                    processing_message = %s
                WHERE id = %s;
                """,
                (status, stage, percent, resolved_message, document_id),
            )

    def queue_document(
        self,
        space_id: str,
        *,
        filename: str | None,
        content_type: str | None,
        raw: bytes,
    ) -> KnowledgeDocument:
        text = raw.decode("utf-8", errors="ignore").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Uploaded file produced no usable text.")

        document_id = str(uuid4())
        embedding_row = self._embedding_row()
        status, stage, percent, progress_message = _document_progress("QUEUED")

        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM knowledge_spaces WHERE id = %s;", (space_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Knowledge space not found.")
            cur.execute(
                """
                INSERT INTO knowledge_documents (
                  id, space_id, filename, content_type, processing_status, processing_stage,
                  processing_progress_percent, processing_message, content, chunk_count,
                  embedding_provider, embedding_model, embedding_dimension
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                RETURNING
                  id, space_id, filename, content_type, processing_status, processing_stage,
                  processing_progress_percent, processing_message, content, chunk_count, created_at;
                """,
                (
                    document_id,
                    space_id,
                    filename or "document.txt",
                    content_type or "application/octet-stream",
                    status,
                    stage,
                    percent,
                    progress_message,
                    text,
                    0,
                    embedding_row["embedding_provider"],
                    embedding_row["embedding_model"],
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Failed to store uploaded document.")
            return self._row_to_document(dict(row))

    def process_document(self, document_id: str) -> None:
        row = self._get_document_row(document_id)
        if row is None:
            return

        try:
            self._update_document_progress(document_id, "EXTRACTING")
            content = str(row["content"] or "").strip()
            if not content:
                raise ValueError("Uploaded file produced no usable text.")

            self._update_document_progress(document_id, "CHUNKING")
            knowledge_settings = self.get_knowledge_settings()
            labeled_chunks = _chunk_text_with_labels(
                content,
                chunk_size=knowledge_settings.chunk_size,
                chunk_overlap=knowledge_settings.chunk_overlap,
                markdown_aware=knowledge_settings.enable_markdown_chunking,
            )
            if not labeled_chunks:
                raise ValueError("Uploaded file produced no usable chunks.")

            self._update_document_progress(document_id, "EMBEDDING")
            embedding_row = self._embedding_row()
            provider_name = row.get("embedding_provider") or embedding_row["embedding_provider"]
            model_name = row.get("embedding_model") or embedding_row["embedding_model"]
            provider = build_embedding_provider(
                provider_name,
                model_name=model_name,
                api_key=embedding_row["embedding_api_key"],
                base_url=embedding_row["embedding_base_url"] or self._default_ollama_base_url,
            )
            embeddings = [provider.embed_one(chunk_text) for _, chunk_text in labeled_chunks]
            embedding_dimension = len(embeddings[0]) if embeddings else 0

            self._update_document_progress(document_id, "FINALIZING")
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM knowledge_chunks WHERE document_id = %s;", (document_id,))
                for (section_label, chunk_text), embedding in zip(labeled_chunks, embeddings, strict=True):
                    cur.execute(
                        """
                        INSERT INTO knowledge_chunks (
                          id, document_id, space_id, chunk_text, section_label, embedding, embedding_dimension
                        )
                        VALUES (%s, %s, %s, %s, %s, %s::vector, %s);
                        """,
                        (
                            str(uuid4()),
                            document_id,
                            row["space_id"],
                            chunk_text,
                            section_label,
                            json.dumps(embedding),
                            embedding_dimension,
                        ),
                    )
                status, stage, percent, progress_message = _document_progress("READY")
                cur.execute(
                    """
                    UPDATE knowledge_documents
                    SET processing_status = %s,
                        processing_stage = %s,
                        processing_progress_percent = %s,
                        processing_message = %s,
                        chunk_count = %s,
                        embedding_provider = %s,
                        embedding_model = %s,
                        embedding_dimension = %s
                    WHERE id = %s;
                    """,
                    (
                        status,
                        stage,
                        percent,
                        progress_message,
                        len(labeled_chunks),
                        provider_name,
                        model_name,
                        embedding_dimension,
                        document_id,
                    ),
                )
        except Exception as exc:
            failure_message = _friendly_processing_message(str(exc))
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE knowledge_documents
                    SET processing_status = 'FAILED',
                        processing_stage = 'FAILED',
                        processing_progress_percent = GREATEST(processing_progress_percent, 5),
                        processing_message = %s,
                        chunk_count = 0
                    WHERE id = %s;
                    """,
                    (failure_message, document_id),
                )

    def select_space(self, session_id: str, chat_id: str, space_id: str) -> Chat:
        _ = self.get_chat(session_id, chat_id)
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM knowledge_spaces WHERE id = %s;", (space_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Knowledge space not found.")
            cur.execute(
                """
                UPDATE assistant_chats
                SET knowledge_space_id = %s, updated_at = now()
                WHERE id = %s AND session_id = %s
                RETURNING id, session_id, title, knowledge_space_id, created_at, updated_at;
                """,
                (space_id, chat_id, session_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Chat not found.")
            return self._row_to_chat(row)

    def clear_selection(self, session_id: str, chat_id: str) -> Chat:
        _ = self.get_chat(session_id, chat_id)
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE assistant_chats
                SET knowledge_space_id = NULL, updated_at = now()
                WHERE id = %s AND session_id = %s
                RETURNING id, session_id, title, knowledge_space_id, created_at, updated_at;
                """,
                (chat_id, session_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Chat not found.")
            return self._row_to_chat(row)

    def _retrieve(self, space_id: str, message: str) -> list[Citation]:
        rewritten_query = self._augment_query(message)
        query_embedding = self._embed_text(rewritten_query)
        embedding_dimension = len(query_embedding)
        knowledge_settings = self.get_knowledge_settings()
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  kc.id,
                  kd.filename,
                  kc.section_label,
                  kc.chunk_text,
                  1 - (kc.embedding <=> %s::vector) AS score
                FROM knowledge_chunks kc
                JOIN knowledge_documents kd ON kd.id = kc.document_id
                WHERE kc.space_id = %s
                  AND kd.processing_status = 'READY'
                  AND kc.embedding_dimension = %s
                ORDER BY kc.embedding <=> %s::vector
                LIMIT %s;
                """,
                (
                    json.dumps(query_embedding),
                    space_id,
                    embedding_dimension,
                    json.dumps(query_embedding),
                    knowledge_settings.retrieval_top_k,
                ),
            )
            vector_rows = cur.fetchall()
            lexical_rows: list[dict[str, Any]] = []
            if knowledge_settings.hybrid_search_enabled and rewritten_query.strip():
                cur.execute(
                    """
                    SELECT
                      kc.id,
                      kd.filename,
                      kc.section_label,
                      kc.chunk_text,
                      ts_rank_cd(
                        to_tsvector('simple', kc.chunk_text),
                        websearch_to_tsquery('simple', %s)
                      ) AS score
                    FROM knowledge_chunks kc
                    JOIN knowledge_documents kd ON kd.id = kc.document_id
                    WHERE kc.space_id = %s
                      AND kd.processing_status = 'READY'
                      AND to_tsvector('simple', kc.chunk_text) @@ websearch_to_tsquery('simple', %s)
                    ORDER BY score DESC
                    LIMIT %s;
                    """,
                    (
                        rewritten_query,
                        space_id,
                        rewritten_query,
                        knowledge_settings.retrieval_top_k,
                    ),
                )
                lexical_rows = cur.fetchall()

        rows = vector_rows
        if lexical_rows:
            seen: dict[str, dict[str, Any]] = {}
            for row in vector_rows + lexical_rows:
                seen.setdefault(str(row["id"]), dict(row))
            fused_scores: dict[str, float] = {}
            lexical_weight = float(knowledge_settings.hybrid_bm25_weight)
            vector_weight = 1.0 - lexical_weight
            for index, row in enumerate(vector_rows, start=1):
                fused_scores[str(row["id"])] = fused_scores.get(str(row["id"]), 0.0) + vector_weight / (60 + index)
            for index, row in enumerate(lexical_rows, start=1):
                fused_scores[str(row["id"])] = fused_scores.get(str(row["id"]), 0.0) + lexical_weight / (60 + index)
            rows = sorted(
                (dict(seen[row_id], score=score) for row_id, score in fused_scores.items()),
                key=lambda row: float(row["score"]),
                reverse=True,
            )[: knowledge_settings.retrieval_top_k]

        apply_threshold = not lexical_rows
        citations: list[Citation] = []
        for index, row in enumerate(rows, start=1):
            score = float(row["score"] or 0.0)
            if apply_threshold and score < knowledge_settings.relevance_threshold:
                continue
            citations.append(
                Citation(
                    id=str(index),
                    title=row["filename"],
                    excerpt=row["chunk_text"][:240],
                    section=row.get("section_label"),
                )
            )
        return citations

    def append_user_message(self, session_id: str, chat_id: str, content: str) -> ChatMessage:
        chat = self.get_chat(session_id, chat_id)
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            if chat.title == "New chat":
                cur.execute(
                    """
                    UPDATE assistant_chats
                    SET title = %s, updated_at = now()
                    WHERE id = %s;
                    """,
                    (content.strip()[:60] or "New chat", chat_id),
                )
            cur.execute(
                """
                INSERT INTO assistant_chat_messages (id, chat_id, role, content, grounded, citations)
                VALUES (%s, %s, 'USER', %s, FALSE, '[]'::jsonb)
                RETURNING id, role, content, grounded, citations, feedback_vote, created_at;
                """,
                (str(uuid4()), chat_id, content),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Failed to store user message.")
            cur.execute("UPDATE assistant_chats SET updated_at = now() WHERE id = %s;", (chat_id,))
            return self._row_to_message(row)

    def append_assistant_message(self, session_id: str, chat_id: str, content: str) -> ChatMessage:
        chat = self.get_chat(session_id, chat_id)
        citations = self._retrieve(chat.knowledge_space_id, content) if chat.knowledge_space_id else []
        history = self.list_messages(session_id, chat_id)
        reply = self._generate_answer(prompt=content, context="", citations=citations, history=history)
        grounded = len(citations) > 0

        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO assistant_chat_messages (id, chat_id, role, content, grounded, citations)
                VALUES (%s, %s, 'ASSISTANT', %s, %s, %s)
                RETURNING id, role, content, grounded, citations, feedback_vote, created_at;
                """,
                (
                    str(uuid4()),
                    chat_id,
                    reply,
                    grounded,
                    Json([citation.model_dump() for citation in citations]),
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Failed to store assistant message.")
            cur.execute("UPDATE assistant_chats SET updated_at = now() WHERE id = %s;", (chat_id,))
            return self._row_to_message(row)

    def stream_assistant_reply(self, session_id: str, chat_id: str, content: str):
        chat = self.get_chat(session_id, chat_id)
        citations = self._retrieve(chat.knowledge_space_id, content) if chat.knowledge_space_id else []
        history = self.list_messages(session_id, chat_id)
        parts: list[str] = []
        yield {"type": "grounded", "value": bool(citations)}

        for event in self._build_generation_events(prompt=content, history=history, citations=citations):
            if event.kind == "token" and event.token:
                parts.append(event.token)
                yield {"type": "token", "token": event.token}
            elif event.kind == "thinking" and self._show_thinking_overlay():
                yield {"type": "thinking", "value": bool(event.value)}
            elif event.kind == "thinking_text" and event.text and self._show_thinking_overlay():
                yield {"type": "thinking_text", "text": event.text}

        reply = "".join(parts).strip()
        if not reply:
            raise HTTPException(status_code=503, detail="Model returned no content.")
        grounded = len(citations) > 0

        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO assistant_chat_messages (id, chat_id, role, content, grounded, citations)
                VALUES (%s, %s, 'ASSISTANT', %s, %s, %s)
                RETURNING id, role, content, grounded, citations, feedback_vote, created_at;
                """,
                (
                    str(uuid4()),
                    chat_id,
                    reply,
                    grounded,
                    Json([citation.model_dump() for citation in citations]),
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Failed to store assistant message.")
            cur.execute("UPDATE assistant_chats SET updated_at = now() WHERE id = %s;", (chat_id,))
            message = self._row_to_message(row)

        yield {"type": "message", "message": message.model_dump()}
        if citations:
            yield {"type": "sources", "chunks": [citation.model_dump() for citation in citations]}

    def regenerate(self, session_id: str, chat_id: str) -> ChatMessage:
        history = self.list_messages(session_id, chat_id)
        last_user = next((message for message in reversed(history) if message.role == "USER"), None)
        if last_user is None:
            raise HTTPException(status_code=400, detail="No user message to regenerate from.")
        return self.append_assistant_message(session_id, chat_id, last_user.content)

    def stream_regenerated_reply(self, session_id: str, chat_id: str):
        history = self.list_messages(session_id, chat_id)
        last_user = next((message for message in reversed(history) if message.role == "USER"), None)
        if last_user is None:
            raise HTTPException(status_code=400, detail="No user message to regenerate from.")
        yield from self.stream_assistant_reply(session_id, chat_id, last_user.content)

    def set_message_feedback(self, session_id: str, message_id: str, vote: Optional[FeedbackVote]) -> ChatMessage:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE assistant_chat_messages AS m
                SET feedback_vote = %s
                FROM assistant_chats AS c
                WHERE m.chat_id = c.id
                  AND m.id = %s
                  AND c.session_id = %s
                  AND c.deleted_at IS NULL
                  AND m.role = 'ASSISTANT'
                RETURNING m.id, m.role, m.content, m.grounded, m.citations, m.feedback_vote, m.created_at;
                """,
                (vote, message_id, session_id),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Message not found.")
            return self._row_to_message(row)

    def get_ollama_models(self, base_url: Optional[str] = None) -> list[dict[str, Any]]:
        return list_ollama_models(base_url or self._default_ollama_base_url)

    def get_ollama_health(self, base_url: Optional[str] = None) -> dict[str, Any]:
        return check_ollama_health(base_url or self._default_ollama_base_url)

    def pull_ollama_model(self, model: str, base_url: Optional[str] = None):
        target = model.strip()
        if not target:
            raise HTTPException(status_code=400, detail="Model is required.")
        return pull_ollama_model(base_url or self._default_ollama_base_url, target)

    def get_openrouter_models(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> list[dict[str, Any]]:
        effective_api_key = api_key or self._generation_row().get("generation_api_key")
        if not effective_api_key:
            return [
                ProviderModelOption(
                    id=OPENROUTER_DEFAULT_MODEL,
                    label=f"{OPENROUTER_DEFAULT_MODEL} (default)",
                    supports_reasoning=True,
                ).model_dump()
            ]
        try:
            models = list_openrouter_models(api_key=str(effective_api_key), base_url=base_url)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Cannot reach OpenRouter: {exc}") from exc
        return [
            ProviderModelOption(
                id=str(item.get("id") or item.get("name") or ""),
                label=str(item.get("name") or item.get("id") or ""),
                supports_reasoning=bool(
                    isinstance(item.get("supported_parameters"), list)
                    and (
                        "reasoning" in item["supported_parameters"]
                        or "include_reasoning" in item["supported_parameters"]
                    )
                ),
            ).model_dump()
            for item in models
            if str(item.get("id") or item.get("name") or "").strip()
        ]


def build_store() -> MemoryAssistantStore | PostgresAssistantStore:
    backend = os.getenv("ASSISTANT_STORE_BACKEND")
    if backend == "memory":
        return MemoryAssistantStore()
    if psycopg2 is None:
        return MemoryAssistantStore()
    if backend == "postgres" or os.getenv("DATABASE_URL"):
        return PostgresAssistantStore()
    return MemoryAssistantStore()


store = build_store()
