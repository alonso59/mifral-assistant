# Assistant

Standalone mirror of the classroom AI assistant stack.

`Assistant/` keeps the classroom chat and retrieval behavior that matters for local use:
- persistent browser-scoped chats
- one optional selected knowledge space per chat
- generation and embedding settings
- markdown-aware ingestion, embeddings, retrieval, and citations
- reasoning/thinking summaries in the chat UI
- responsive single-sidebar shell without auth, roles, or classroom wrappers

This repo is intentionally wrapper-free. It excludes classroom auth, roles, lesson routing, and workspace chrome.

## Local Requirement

Ollama must be installed and running on the host machine outside Docker.

Tracked/stored Assistant config continues to use:

```text
http://localhost:11434
```

When the Assistant backend itself runs inside Docker, localhost is rewritten at runtime to `host.docker.internal` so the contract stays stable for the UI and persisted settings.

## Run With Docker

```bash
cd Assistant
cp .env.example .env
docker compose up --build
```

Services:
- `frontend`
- `backend`
- `postgres`

Endpoints:
- frontend: `http://localhost:${FRONTEND_PORT}`
- backend: `http://localhost:${BACKEND_PORT}`

Notes:
- backend and frontend health do not depend on Ollama being online
- Ollama health/model list/pull endpoints will report normalized errors when Ollama is unavailable
- `compose.gpu.yaml` is only an additive Docker override; it does not start Ollama

## Run Backend Locally

```bash
cd Assistant/backend
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8100
```

## Run Frontend Locally

```bash
cd Assistant/frontend
npm install
npm run dev
```

Set `BACKEND_INTERNAL_URL=http://localhost:8100` for the frontend when needed.

## Standalone Scope

- no auth or roles
- chats isolated by browser session via `X-Session-Id`
- instance-wide settings editable in-app
- knowledge retrieval constrained to the selected knowledge space only
- general-answer fallback when retrieval is weak or absent
- provider reasoning summaries displayed only when `show_thinking_overlay` is enabled

## Validation

Backend:

```bash
cd Assistant/backend
pytest -q
```

Frontend:

```bash
cd Assistant/frontend
npm test
```
