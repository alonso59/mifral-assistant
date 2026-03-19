# MIGRATION

## Phase 0: Contract First
Objective:
- create assistant-specific product and software contracts

Reuse:
- chat, retrieval, provider, and settings concepts from the classroom app

Drop:
- auth, roles, classroom structure, lesson binding, workspace shell

Validation gate:
- docs exist and define the single-sidebar interaction model

Rollback point:
- remove `Assistant/docs` only

## Phase 1: Isolate Runtime
Objective:
- extract reusable runtime concepts into assistant-safe modules

Reuse:
- chat streaming pattern
- retrieval flow
- model and knowledge settings concepts

Drop:
- lesson and class authorization
- draft/published gates
- hidden prompt rules

Validation gate:
- backend can boot independently

Rollback point:
- remove `Assistant/backend`

## Phase 2: Backend Contract
Objective:
- implement standalone assistant APIs for chats, knowledge, and settings

Reuse:
- request/response envelope shape
- SSE streaming semantics

Drop:
- classroom routes and payload dependencies

Validation gate:
- backend tests cover chat lifecycle, knowledge selection, and upload flow

Rollback point:
- revert `Assistant/backend/app` and tests

## Phase 3: Frontend Shell
Objective:
- build standalone SvelteKit shell with one single sidebar

Reuse:
- muted editorial visual language
- overlay settings patterns

Drop:
- classroom routes
- rail + workspace + right-panel shell

Validation gate:
- frontend tests cover `New chat`, `New knowledge`, knowledge expand/collapse, and selection state

Rollback point:
- revert `Assistant/frontend`

## Phase 4: Knowledge and RAG Cutover
Objective:
- replace lesson/material ownership with knowledge-space ownership

Reuse:
- chunking and retrieval configuration

Drop:
- lesson-bound retrieval

Validation gate:
- upload, chunk, retrieval, and citation flow work end to end

Rollback point:
- disable knowledge selection and upload flow

## Phase 5: Handoff
Objective:
- document structure, startup, and boundaries

Validation gate:
- `Assistant/README.md` matches the delivered scaffold

Rollback point:
- keep subtree but mark as experimental
