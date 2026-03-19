from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import psycopg2
from fastapi import HTTPException, UploadFile
from psycopg2.extras import Json, RealDictCursor

from app.embedding import build_embedding_provider
from app.generation import build_generation_provider, check_ollama_health, list_ollama_models, pull_ollama_model
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
    SystemSettings,
)


DEFAULT_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
DEFAULT_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
DEFAULT_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://assistant:assistant@postgres:5432/assistant",
)


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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
                provider="ollama",
                model=DEFAULT_EMBEDDING_MODEL,
                base_url=DEFAULT_OLLAMA_BASE_URL,
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

    async def add_document(self, space_id: str, upload: UploadFile) -> KnowledgeDocument:
        record = self.spaces.get(space_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Knowledge space not found.")
        raw = await upload.read()
        text = raw.decode("utf-8", errors="ignore").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Uploaded file produced no usable text.")
        chunks = _chunk_text(
            text,
            chunk_size=self.knowledge_settings.chunk_size,
            chunk_overlap=self.knowledge_settings.chunk_overlap,
        )
        document = KnowledgeDocument(
            id=str(uuid4()),
            space_id=space_id,
            filename=upload.filename or "document.txt",
            content_type=upload.content_type or "application/octet-stream",
            processing_status="READY",
            content=text,
            chunk_count=len(chunks),
            created_at=utc_iso(),
        )
        record["documents"].append(document)
        record["chunks"].extend(
            {"id": str(uuid4()), "document_id": document.id, "text": chunk}
            for chunk in chunks
        )
        return document

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
                )
            )
            if len(citations) >= self.knowledge_settings.retrieval_top_k:
                break
        return citations

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

    def regenerate(self, session_id: str, chat_id: str) -> ChatMessage:
        history = self.list_messages(session_id, chat_id)
        last_user = next((message for message in reversed(history) if message.role == "USER"), None)
        if last_user is None:
            raise HTTPException(status_code=400, detail="No user message to regenerate from.")
        return self.append_assistant_message(session_id, chat_id, last_user.content)

    def set_message_feedback(self, session_id: str, message_id: str, vote: Optional[FeedbackVote]) -> ChatMessage:
        for chat in self.chats.get(session_id, []):
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
            default_models.append({"name": DEFAULT_EMBEDDING_MODEL})
        unique: dict[str, dict[str, Any]] = {}
        for item in default_models:
            unique[item["name"]] = item
        return list(unique.values())

    def get_ollama_health(self, base_url: Optional[str] = None) -> dict[str, Any]:
        models = self.get_ollama_models(base_url)
        return {"ok": True, "model_count": len(models)}

    def pull_ollama_model(self, model: str, base_url: Optional[str] = None):
        target = model.strip()
        if not target:
            raise HTTPException(status_code=400, detail="Model is required.")
        yield json.dumps({"status": "success", "completed": 1, "total": 1, "model": target})


class PostgresAssistantStore:
    def __init__(self) -> None:
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
                  hybrid_search_enabled BOOLEAN NOT NULL,
                  rag_template TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS system_settings (
                  id SMALLINT PRIMARY KEY DEFAULT 1,
                  app_name TEXT NOT NULL,
                  theme TEXT NOT NULL
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
                  content TEXT NOT NULL,
                  chunk_count INTEGER NOT NULL DEFAULT 0,
                  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );

                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedding_provider TEXT;
                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedding_model TEXT;
                ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER;

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                  id TEXT PRIMARY KEY,
                  document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
                  space_id TEXT NOT NULL REFERENCES knowledge_spaces(id) ON DELETE CASCADE,
                  chunk_text TEXT NOT NULL,
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
                  1, 'ollama', %s, 'ollama', %s,
                  NULL, %s, 'You are a helpful AI assistant.',
                  0.7, 1024, 8192, FALSE,
                  NULL, %s
                )
                ON CONFLICT (id) DO NOTHING;
                """,
                (DEFAULT_CHAT_MODEL, DEFAULT_EMBEDDING_MODEL, DEFAULT_OLLAMA_BASE_URL, DEFAULT_OLLAMA_BASE_URL),
            )
            cur.execute(
                """
                UPDATE model_settings
                SET embedding_provider = COALESCE(embedding_provider, 'ollama'),
                    generation_base_url = COALESCE(generation_base_url, %s),
                    embedding_base_url = COALESCE(embedding_base_url, %s),
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
                INSERT INTO knowledge_settings (
                  id, chunk_size, chunk_overlap, retrieval_top_k, relevance_threshold,
                  hybrid_search_enabled, rag_template
                )
                VALUES (
                  1, 1000, 120, 5, 0.0, FALSE,
                  'Use the provided context when it is relevant. If the context is insufficient, answer honestly and say what is missing.'
                )
                ON CONFLICT (id) DO NOTHING;
                """
            )
            cur.execute(
                """
                INSERT INTO system_settings (id, app_name, theme)
                VALUES (1, 'Assistant', 'light')
                ON CONFLICT (id) DO NOTHING;
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
            return ModelSettings(
                generation=GenerationSettings(
                    provider=row["provider"],
                    model=row["model"],
                    api_key_set=bool(row["generation_api_key"]),
                    base_url=row["generation_base_url"],
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
                    base_url=row["embedding_base_url"],
                ),
            )

    def set_model_settings(self, value: ModelSettings, *, generation_api_key: str | None, embedding_api_key: str | None) -> ModelSettings:
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
                        value.generation.base_url,
                        value.generation.system_prompt,
                        value.generation.temperature,
                        value.generation.max_tokens,
                        value.generation.context_max_tokens,
                        value.generation.auto_compress,
                        value.embedding.provider,
                        value.embedding.model,
                        embedding_api_key,
                        value.embedding.base_url,
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
                        value.generation.base_url,
                        value.generation.system_prompt,
                        value.generation.temperature,
                        value.generation.max_tokens,
                        value.generation.context_max_tokens,
                        value.generation.auto_compress,
                        value.embedding.provider,
                        value.embedding.model,
                        embedding_api_key,
                        value.embedding.base_url,
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
                       hybrid_search_enabled, rag_template
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
                    hybrid_search_enabled = %s,
                    rag_template = %s
                WHERE id = 1;
                """,
                (
                    value.chunk_size,
                    value.chunk_overlap,
                    value.retrieval_top_k,
                    value.relevance_threshold,
                    value.hybrid_search_enabled,
                    value.rag_template,
                ),
            )
        return self.get_knowledge_settings()

    def get_system_settings(self) -> SystemSettings:
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT app_name, theme FROM system_settings WHERE id = 1;")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="System settings are missing.")
            return SystemSettings(**row)

    def set_system_settings(self, value: SystemSettings) -> SystemSettings:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE system_settings
                SET app_name = %s, theme = %s
                WHERE id = 1;
                """,
                (value.app_name, value.theme),
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
            return dict(row)

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
            return dict(row)

    def _embed_text(self, text: str) -> list[float]:
        row = self._embedding_row()
        provider = build_embedding_provider(
            row["embedding_provider"],
            model_name=row["embedding_model"],
            api_key=row["embedding_api_key"],
            base_url=row["embedding_base_url"] or self._default_ollama_base_url,
        )
        return provider.embed_one(text)

    def _generate_answer(self, *, prompt: str, context: str, citations: list[Citation], history: list[ChatMessage]) -> str:
        row = self._generation_row()
        citation_guide = "\n".join(f"[{citation.id}] {citation.title}: {citation.excerpt}" for citation in citations)
        rag_prompt = self.get_knowledge_settings().rag_template
        system_prompt = row["system_prompt"] or "You are a helpful AI assistant."
        if rag_prompt:
            system_prompt = f"{system_prompt}\n\n{rag_prompt}"

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
                "content": (
                    f"{prompt}\n\nRetrieved context:\n{context or 'No retrieved context.'}\n\n"
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
                SELECT id, space_id, filename, content_type, processing_status, content, chunk_count, created_at
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

    async def add_document(self, space_id: str, upload: UploadFile) -> KnowledgeDocument:
        raw = await upload.read()
        text = raw.decode("utf-8", errors="ignore").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Uploaded file produced no usable text.")

        knowledge_settings = self.get_knowledge_settings()
        document_id = str(uuid4())
        chunks = _chunk_text(
            text,
            chunk_size=knowledge_settings.chunk_size,
            chunk_overlap=knowledge_settings.chunk_overlap,
        )
        embedding_row = self._embedding_row()

        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT 1 FROM knowledge_spaces WHERE id = %s;", (space_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Knowledge space not found.")
            cur.execute(
                """
                INSERT INTO knowledge_documents (
                  id, space_id, filename, content_type, processing_status, content, chunk_count,
                  embedding_provider, embedding_model, embedding_dimension
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)
                RETURNING id, space_id, filename, content_type, processing_status, content, chunk_count, created_at;
                """,
                (
                    document_id,
                    space_id,
                    upload.filename or "document.txt",
                    upload.content_type or "application/octet-stream",
                    "PROCESSING",
                    text,
                    0,
                    embedding_row["embedding_provider"],
                    embedding_row["embedding_model"],
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=500, detail="Failed to store uploaded document.")

        try:
            provider = build_embedding_provider(
                embedding_row["embedding_provider"],
                model_name=embedding_row["embedding_model"],
                api_key=embedding_row["embedding_api_key"],
                base_url=embedding_row["embedding_base_url"] or self._default_ollama_base_url,
            )
            embeddings = [provider.embed_one(chunk) for chunk in chunks]
            embedding_dimension = len(embeddings[0]) if embeddings else 0
            with self._connect() as conn, conn.cursor() as cur:
                for chunk_text, embedding in zip(chunks, embeddings):
                    cur.execute(
                        """
                        INSERT INTO knowledge_chunks (id, document_id, space_id, chunk_text, embedding, embedding_dimension)
                        VALUES (%s, %s, %s, %s, %s::vector, %s);
                        """,
                        (
                            str(uuid4()),
                            document_id,
                            space_id,
                            chunk_text,
                            json.dumps(embedding),
                            embedding_dimension,
                        ),
                    )
                cur.execute(
                    """
                    UPDATE knowledge_documents
                    SET processing_status = 'READY',
                        chunk_count = %s,
                        embedding_dimension = %s
                    WHERE id = %s;
                    """,
                    (len(chunks), embedding_dimension, document_id),
                )
            row["processing_status"] = "READY"
            row["chunk_count"] = len(chunks)
        except Exception as exc:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE knowledge_documents
                    SET processing_status = 'FAILED'
                    WHERE id = %s;
                    """,
                    (document_id,),
                )
            raise HTTPException(status_code=502, detail=f"Failed to process document: {exc}") from exc

        return self._row_to_document(row)

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
        query_embedding = self._embed_text(message)
        embedding_dimension = len(query_embedding)
        knowledge_settings = self.get_knowledge_settings()
        with self._connect() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                  kc.id,
                  kd.filename,
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
            rows = cur.fetchall()

        citations: list[Citation] = []
        for index, row in enumerate(rows, start=1):
            score = float(row["score"] or 0.0)
            if score < knowledge_settings.relevance_threshold:
                continue
            citations.append(
                Citation(
                    id=str(index),
                    title=row["filename"],
                    excerpt=row["chunk_text"][:240],
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
        context = "\n\n".join(f"[{citation.id}] {citation.excerpt}" for citation in citations)
        history = self.list_messages(session_id, chat_id)
        reply = self._generate_answer(prompt=content, context=context, citations=citations, history=history)
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

    def regenerate(self, session_id: str, chat_id: str) -> ChatMessage:
        history = self.list_messages(session_id, chat_id)
        last_user = next((message for message in reversed(history) if message.role == "USER"), None)
        if last_user is None:
            raise HTTPException(status_code=400, detail="No user message to regenerate from.")
        return self.append_assistant_message(session_id, chat_id, last_user.content)

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


def build_store() -> MemoryAssistantStore | PostgresAssistantStore:
    backend = os.getenv("ASSISTANT_STORE_BACKEND")
    if backend == "memory":
        return MemoryAssistantStore()
    if backend == "postgres" or os.getenv("DATABASE_URL"):
        return PostgresAssistantStore()
    return MemoryAssistantStore()


store = build_store()
