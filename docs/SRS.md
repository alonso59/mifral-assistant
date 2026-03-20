# SRS

## Purpose
This document defines the standalone Assistant contract for frontend behavior, backend APIs, persistence, knowledge ingestion, retrieval, and external-provider topology.

## System Overview
- Frontend: SvelteKit + TypeScript
- Backend: FastAPI
- Data platform: PostgreSQL + pgvector in deployed mode, memory store for lightweight tests
- Chat transport: Server-Sent Events
- Session model: browser-generated `session_id` sent as `X-Session-Id`
- Local model dependency: host-installed Ollama outside Docker

## Session Model
- The frontend generates a persistent browser session ID on first load.
- The session ID is reused on every API call.
- Chats are isolated per session ID.
- Knowledge spaces and settings are shared instance-wide because auth and roles are removed in the standalone replica.

## Frontend Contract
- Route model:
  - `/` renders the full assistant shell and active chat
- Sidebar behavior:
  - one single continuous sidebar
  - desktop keeps the sidebar docked
  - narrow widths collapse the sidebar into a drawer or sheet
  - `New chat` creates and opens a fresh empty chat
  - chat history stays usable while knowledge is expanded
  - `Knowledge` is a collapsible section within the same sidebar
  - `New knowledge` opens the inline knowledge-space flow
  - selecting a knowledge space applies it to the active chat
  - clearing selection returns the chat to general mode
  - exactly zero or one knowledge space may be selected for a chat
- Transcript behavior:
  - token streaming updates the latest in-flight assistant message
  - grounded warning renders when a knowledge space is selected but no grounded citations support the answer
  - citations are disclosed after completion
  - reasoning summaries render only when `show_thinking_overlay` is enabled
  - users can regenerate the latest assistant answer
  - users can stop an in-flight stream
  - composer focus is restored after send/regenerate completion
- Settings overlay:
  - opens as a modal overlay
  - scales to the viewport on narrow screens
  - tabs: `Model`, `Knowledge`, `System`

## Backend Contract

### Chat
- `GET /api/v1/chats`
- `POST /api/v1/chats`
- `GET /api/v1/chats/{chat_id}/messages`
- `POST /api/v1/chats/{chat_id}/messages/stream`
- `POST /api/v1/chats/{chat_id}/regenerate`
- `PATCH /api/v1/chats/{chat_id}`
- `DELETE /api/v1/chats/{chat_id}`
- `DELETE /api/v1/chats/{chat_id}/knowledge-selection`
- `POST /api/v1/messages/{message_id}/feedback`

### Knowledge
- `GET /api/v1/knowledge-spaces`
- `POST /api/v1/knowledge-spaces`
- `PATCH /api/v1/knowledge-spaces/{space_id}`
- `DELETE /api/v1/knowledge-spaces/{space_id}`
- `POST /api/v1/knowledge-spaces/{space_id}/documents`
- `POST /api/v1/knowledge-spaces/{space_id}/select`

### Settings
- `GET /api/v1/settings/model`
- `PUT /api/v1/settings/model`
- `GET /api/v1/settings/knowledge`
- `PUT /api/v1/settings/knowledge`
- `GET /api/v1/settings/system`
- `PUT /api/v1/settings/system`
- `GET /api/v1/settings/model/ollama/models`
- `GET /api/v1/settings/model/ollama/health`
- `POST /api/v1/settings/model/ollama/pull`
- `GET /api/v1/settings/model/openrouter/models`

## SSE Contract
`POST /api/v1/chats/{chat_id}/messages/stream` and `POST /api/v1/chats/{chat_id}/regenerate` emit ordered JSON events through SSE.

Event types:
- `start`
- `grounded`
- `thinking`
- `thinking_text`
- `token`
- `message`
- `sources`
- `done`
- `error`

Semantics:
- `grounded` indicates whether retrieval produced supporting citations for the response
- `thinking` and `thinking_text` surface provider-supplied reasoning summaries only
- `message` contains the persisted final assistant message
- `sources` contains citation payloads for disclosure in the UI
- `error` is normalized so provider failures do not leave the stream hanging

## Settings Contract

### Model Settings
- generation settings include provider, model, API key, base URL, system prompt, temperature, max tokens, context window, and auto-compress
- embedding settings include provider, model, API key, and base URL
- generation and embedding config are stored separately

### Knowledge Settings
- `chunk_size`
- `chunk_overlap`
- `retrieval_top_k`
- `relevance_threshold`
- `enable_markdown_chunking`
- `query_augmentation`
- `hybrid_search_enabled`
- `hybrid_bm25_weight`
- `rag_template`

### System Settings
- `app_name`
- `theme`
- `show_thinking_overlay`

## Persistence Model
- `assistant_sessions`
- `assistant_chats`
  - soft-deleted via `deleted_at`
  - selected `knowledge_space_id` nullable
- `assistant_chat_messages`
  - `USER` and `ASSISTANT`
  - grounded flag
  - citations JSON
  - feedback vote
- `knowledge_spaces`
- `knowledge_documents`
  - upload metadata
  - extracted text
  - processing status
  - embedding provider/model metadata
- `knowledge_chunks`
  - chunk text
  - optional markdown section label
  - embedding vector
  - embedding dimension
- settings tables for model, knowledge, and system state

## Retrieval Behavior
- at most one knowledge space may be selected for a chat
- retrieval searches only the selected knowledge space
- retrieval can use query augmentation before embedding lookup
- knowledge ingestion can split markdown by headings before chunking
- retrieval can combine vector search with lexical BM25-style ranking
- relevance thresholding filters pure vector results
- when retrieval is weak or absent, chat still returns a general answer
- citations are emitted only when grounded support is available

## Ollama Topology
- Ollama is not started by Docker Compose in `Assistant/`
- persisted and API-facing Ollama base URLs remain `http://localhost:11434`
- when the backend runs in Docker, localhost is rewritten at runtime to `host.docker.internal`
- backend and frontend startup must remain healthy even if Ollama is offline

## Acceptance Criteria
- users can create, rename, delete, and switch among chats
- users can upload documents into a knowledge space and retrieve grounded answers from that space
- users can switch between grounded and general chat behavior by selecting or clearing a knowledge space
- settings overlay saves generation, embedding, knowledge, and system values
- reasoning summaries appear only when the system setting allows them
- Ollama health, model list, and model pull work against the external host runtime
- narrow-width layouts keep sidebar, transcript, citations, and composer usable
