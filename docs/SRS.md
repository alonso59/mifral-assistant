# SRS

## Purpose
This document defines the Assistant extraction contract for frontend, backend, session handling, knowledge ingestion, retrieval, and settings behavior.

## System Overview
- Frontend: SvelteKit + TypeScript
- Backend: FastAPI
- Target data platform: PostgreSQL + pgvector
- Chat transport: Server-Sent Events
- Session model: browser-generated `session_id` sent as `X-Session-Id`

## Session Model
- The frontend generates a persistent browser session ID on first load.
- The session ID is stored locally and reused on every API call.
- Chats are isolated per session ID.
- Knowledge spaces and instance settings are shared instance-wide in this scaffold.

## Frontend Contract
- Route model:
  - `/` renders the assistant shell and active chat
- Sidebar behavior:
  - one single continuous sidebar
  - `New chat` creates and opens a fresh empty chat
  - chat history is always visible
  - `Knowledge` is a collapsible section within the same sidebar
  - `New knowledge` opens the inline create-knowledge flow
  - expanding `Knowledge` reveals spaces and uploaded documents inline
  - collapsing `Knowledge` hides that section only
  - selecting a chat loads that conversation in place
  - selecting a knowledge space applies it to the active chat
  - clicking the selected knowledge again, or using clear selection, unselects it
  - exactly zero or one knowledge space may be selected for a chat in v1
- Settings:
  - opened as an overlay modal
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

## Data Model
- `assistant_session`
  - browser session identity
- `assistant_chat`
  - chat title
  - selected `knowledge_space_id` nullable
- `assistant_chat_message`
  - `USER` and `ASSISTANT`
  - grounded flag
  - citations
- `knowledge_space`
  - name
  - description
- `knowledge_document`
  - upload metadata
  - extracted text
  - processing status
- `knowledge_chunk`
  - chunk text
  - retrieval metadata
  - pgvector embedding in production target
- `assistant_settings`
  - model settings
  - chunking/retrieval settings
  - system settings

## Retrieval Behavior
- one selected knowledge space per chat at most
- when selected, retrieval searches only that space
- when no space is selected, chat runs in general mode
- when selected but no relevant chunks are found, chat still returns an answer with no citations
- citations appear only when chunks are matched

## Acceptance Criteria
- users can create multiple chats and switch among them
- users can create a knowledge space from the sidebar
- users can upload at least one text-like document into a knowledge space
- users can select or unselect one knowledge space for a chat
- chat history remains visible while the knowledge section is expanded
- the settings overlay saves model, knowledge, and system values
