# MIGRATION

## Phase 0: Contract Lock
Objective:
- redefine `Assistant/` as a standalone mirror of the classroom AI stack, not an extraction scaffold

Reuse:
- classroom chat/runtime behavior
- classroom settings model for generation, embeddings, RAG, and system controls
- classroom streaming semantics for reasoning, grounded state, citations, and completion

Drop:
- auth
- roles
- classroom wrapper, rail, and lesson navigation

Validation gate:
- `Assistant/docs` and `README.md` describe the standalone mirror and host-installed Ollama requirement

Rollback point:
- revert `Assistant/docs`, `Assistant/README.md`, and this file

## Phase 1: Runtime Parity
Objective:
- make backend chat, retrieval, reasoning, and persistence mirror the classroom pipeline in standalone form

Reuse:
- generation config resolution
- optional query augmentation
- embedding config resolution
- single-space retrieval
- grounded/general decision and source prompt injection
- provider streaming and final metadata persistence

Drop:
- classroom lesson/class fallback
- role-aware settings restrictions

Validation gate:
- backend persists chats, messages, citations, feedback, settings, and knowledge-space selection

Rollback point:
- revert `Assistant/backend/app`

## Phase 2: External Ollama Topology
Objective:
- keep Ollama integration healthy while requiring Ollama to run on the host outside Docker

Reuse:
- Ollama health, model list, and model pull utilities

Drop:
- Docker-managed Ollama service

Validation gate:
- compose stack boots without an Ollama container
- stored config remains `http://localhost:11434`
- backend rewrites localhost to `host.docker.internal` only when it runs inside Docker

Rollback point:
- revert `Assistant/compose*.yaml`, `.env.example`, and Ollama runtime helpers

## Phase 3: Frontend Shell Parity
Objective:
- mirror classroom chat behaviors in the standalone single-sidebar shell

Reuse:
- streaming transcript updates
- grounded warning banner
- citations disclosure
- reasoning disclosure
- regenerate, feedback, copy, empty/loading/error states

Drop:
- classroom wrapper, lesson layout, and auth-dependent affordances

Validation gate:
- standalone UI supports chat lifecycle, knowledge selection, settings, and responsive narrow-width behavior

Rollback point:
- revert `Assistant/frontend`

## Phase 4: Iterative Sync Ledger
Objective:
- keep classroom-to-Assistant replication repeatable across separate repos

Validation gate:
- root `migrate-minimal.md` exists and tracks mirror status by area

Rollback point:
- remove `migrate-minimal.md`
