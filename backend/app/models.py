from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


Role = Literal["USER", "ASSISTANT"]
ProcessingStatus = Literal["PROCESSING", "READY", "FAILED"]
GenerationProvider = Literal["anthropic", "openai", "google", "ollama"]
EmbeddingProvider = Literal["sentence-transformers", "openai", "google", "ollama"]


class Citation(BaseModel):
    id: str
    title: str
    excerpt: str
    section: Optional[str] = None
    page: Optional[int] = None


class ChatMessage(BaseModel):
    id: str
    role: Role
    content: str
    grounded: bool = False
    citations: list[Citation] = Field(default_factory=list)
    created_at: str


class Chat(BaseModel):
    id: str
    session_id: str
    title: str
    knowledge_space_id: Optional[str] = None
    created_at: str
    updated_at: str


class KnowledgeChunk(BaseModel):
    id: str
    document_id: str
    text: str


class KnowledgeDocument(BaseModel):
    id: str
    space_id: str
    filename: str
    content_type: str
    processing_status: ProcessingStatus
    content: str
    chunk_count: int
    created_at: str


class KnowledgeSpace(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: str


class ProviderOption(BaseModel):
    id: str
    label: str
    hint: str
    default_model: str


GENERATION_PROVIDER_OPTIONS = [
    ProviderOption(
        id="anthropic",
        label="Anthropic",
        hint="e.g. claude-haiku-4-5-20251001, claude-sonnet-4-6",
        default_model="claude-haiku-4-5-20251001",
    ),
    ProviderOption(
        id="openai",
        label="OpenAI",
        hint="e.g. gpt-4o-mini, gpt-4o, or a self-hosted OpenAI-compatible model",
        default_model="gpt-4o-mini",
    ),
    ProviderOption(
        id="google",
        label="Google (Gemini)",
        hint="e.g. gemini-2.0-flash, gemini-1.5-flash",
        default_model="gemini-2.0-flash",
    ),
    ProviderOption(
        id="ollama",
        label="Ollama (local)",
        hint="e.g. llama3.2, mistral, phi3",
        default_model="llama3.2",
    ),
]


EMBEDDING_PROVIDER_OPTIONS = [
    ProviderOption(
        id="sentence-transformers",
        label="Sentence Transformers (local CPU)",
        hint="e.g. sentence-transformers/all-MiniLM-L6-v2, all-mpnet-base-v2",
        default_model="sentence-transformers/all-MiniLM-L6-v2",
    ),
    ProviderOption(
        id="openai",
        label="OpenAI / vLLM (API)",
        hint="e.g. text-embedding-3-small, text-embedding-3-large",
        default_model="text-embedding-3-small",
    ),
    ProviderOption(
        id="google",
        label="Google (Gemini)",
        hint="e.g. models/text-embedding-004",
        default_model="models/text-embedding-004",
    ),
    ProviderOption(
        id="ollama",
        label="Ollama (local)",
        hint="e.g. nomic-embed-text, mxbai-embed-large",
        default_model="nomic-embed-text",
    ),
]


class GenerationSettings(BaseModel):
    provider: GenerationProvider = "ollama"
    model: str = "llama3.2"
    api_key_set: bool = False
    base_url: Optional[str] = "http://ollama:11434"
    system_prompt: Optional[str] = "You are a helpful AI assistant."
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=64, le=32768)
    context_max_tokens: int = Field(default=8192, ge=512, le=131072)
    auto_compress: bool = False


class EmbeddingSettings(BaseModel):
    provider: EmbeddingProvider = "ollama"
    model: str = "nomic-embed-text"
    api_key_set: bool = False
    base_url: Optional[str] = "http://ollama:11434"


class ModelSettings(BaseModel):
    generation: GenerationSettings
    embedding: EmbeddingSettings
    generation_provider_options: list[ProviderOption] = Field(
        default_factory=lambda: [option.model_copy() for option in GENERATION_PROVIDER_OPTIONS]
    )
    embedding_provider_options: list[ProviderOption] = Field(
        default_factory=lambda: [option.model_copy() for option in EMBEDDING_PROVIDER_OPTIONS]
    )


class KnowledgeSettings(BaseModel):
    chunk_size: int = 1000
    chunk_overlap: int = 120
    retrieval_top_k: int = 5
    relevance_threshold: float = 0.0
    hybrid_search_enabled: bool = False
    rag_template: str = (
        "Use the provided context when it is relevant. "
        "If the context is insufficient, answer honestly and say what is missing."
    )


class SystemSettings(BaseModel):
    app_name: str = "Assistant"
    theme: Literal["light", "dark", "system"] = "light"
