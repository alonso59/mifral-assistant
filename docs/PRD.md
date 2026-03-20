# PRD

## Product
Assistant

## Summary
Assistant is a standalone replica of the classroom AI assistant flow. It preserves the classroom pipeline, chat behavior, and settings model that matter for single-user local use, while removing auth, roles, classroom navigation, and lesson wrappers.

## Core UX
- one responsive sidebar that contains chat history and knowledge-space management
- `New chat` creates and opens a fresh chat
- `Knowledge` expands inline inside the same sidebar
- each chat can select zero or one knowledge space
- the active chat remains visible while knowledge is expanded or collapsed
- settings open in a viewport-safe overlay with `Model`, `Knowledge`, and `System` tabs
- the transcript mirrors classroom behavior:
  - streaming token updates
  - grounded warning when a knowledge space is selected but retrieval is weak
  - citation disclosure after completion
  - reasoning/thought summaries when enabled
  - regenerate on the latest assistant answer
  - loading, empty, and error states

## Functional Requirements
- users can create, rename, and hide-delete chats
- users can like or dislike assistant messages
- users can copy assistant answers and inspect citations
- users can create, rename, and delete knowledge spaces
- users can upload documents into a knowledge space
- uploaded documents are extracted, chunked, embedded, and stored persistently
- retrieval is limited to the selected knowledge space for the active chat
- chat falls back to general mode when no knowledge space is selected
- chat also falls back to general mode when selected retrieval is weak or insufficient
- users can edit generation, embedding, knowledge, and system settings directly in-app
- Ollama settings support health checks, model listing, and model pull against a host-installed Ollama runtime

## Runtime Requirements
- the standalone backend persists chats, messages, settings, knowledge spaces, documents, chunks, embeddings, citations, and feedback
- the send/regenerate pipeline follows this order:
  1. resolve generation config
  2. optionally augment the retrieval query
  3. resolve embedding config
  4. retrieve from the selected knowledge space
  5. decide grounded versus general mode
  6. inject source context into the prompt only when grounded
  7. stream provider output
  8. persist assistant metadata
- only provider-supplied reasoning summaries are shown
- chain-of-thought is never persisted

## Deployment Constraints
- Ollama must run on the host outside Docker
- stored/configured Ollama URLs remain `http://localhost:11434`
- the backend may rewrite localhost to `host.docker.internal` only at runtime when the backend runs inside Docker

## Non-Goals
- auth or identity management
- multi-user permissions
- classroom lesson/class retrieval fallback
- classroom wrapper, rail, or route structure
- separate mobile information architecture
