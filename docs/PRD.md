# PRD

## Product
Assistant

## Summary
Assistant is a standalone chat-first web product extracted from the classroom application. It keeps the useful AI pipeline pieces only: chat, model settings, embeddings, pgvector-oriented retrieval, knowledge ingestion, and grounded responses.

## Core UX
- one single sidebar modeled after ChatGPT
- `New chat` action near the top
- chat history is the primary sidebar list
- `Knowledge` is an expandable/collapsible section inside the same sidebar
- `New knowledge` action lives with the knowledge section
- users can keep a knowledge space selected or leave all knowledge unselected
- the active chat remains visible while knowledge is expanded or collapsed
- settings open as an overlay window with tabs:
  - `Model`
  - `Knowledge`
  - `System`

## Functional Requirements
- users can create, rename, and delete chats
- users can create knowledge spaces
- users can upload documents into a knowledge space
- uploaded documents are processed into chunks for retrieval
- chat can answer in general mode when no knowledge is selected
- chat can answer with citations when knowledge is selected and relevant matches exist
- users can clear knowledge selection for a chat without leaving the chat view

## Non-Goals
- auth or identity management
- multi-user permissions
- multi-space retrieval in one chat
- advanced observability or admin workflows
