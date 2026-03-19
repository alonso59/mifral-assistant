# Assistant

Standalone assistant extraction scaffold from the classroom product.

This subtree contains:
- `docs/` for the assistant-specific product and software contracts
- `backend/` for a standalone FastAPI API with chat, knowledge, and settings endpoints
- `frontend/` for a standalone SvelteKit UI with a ChatGPT-like single sidebar
- `compose.yaml` plus Dockerfiles for local container runs with PostgreSQL and Ollama

Current implementation scope:
- no auth or roles
- browser-scoped chat sessions via `X-Session-Id`
- chat history list
- expandable `Knowledge` section in the sidebar
- selectable or unselectable knowledge per chat
- settings overlay with `Model`, `Knowledge`, and `System` tabs
- multipart knowledge document upload
- simple extraction/chunking/retrieval scaffold suitable for local validation

This is an extraction-oriented v1 scaffold, not a full production cutover.
The classroom app remains unchanged.

## Run

Docker:

```bash
cd Assistant
cp .env.example .env
docker compose up --build
```

After the stack is up, pull the Ollama models once:

```bash
cd Assistant
docker compose exec ollama ollama pull "${OLLAMA_CHAT_MODEL}"
docker compose exec ollama ollama pull "${OLLAMA_EMBED_MODEL}"
```

GPU-enabled Ollama:

```bash
cd Assistant
cp .env.example .env
docker compose -f compose.yaml -f compose.gpu.yaml up --build
```

Make targets:

```bash
cd Assistant
make up
make up-gpu
make down
```

Endpoints:
- frontend: `http://localhost:${FRONTEND_PORT}`
- backend: `http://localhost:${BACKEND_PORT}`

Included services:
- `frontend`
- `backend`
- `postgres`
- `ollama`

Local configuration lives in:
- `.env` for your machine
- `.env.example` as the tracked template

GPU notes:
- `compose.yaml` is the default CPU-safe stack.
- `compose.gpu.yaml` is an additive override for NVIDIA hosts.
- `make up-gpu` checks for `nvidia-smi` before starting the GPU override.
- Docker GPU support still requires NVIDIA drivers plus NVIDIA Container Toolkit on the host.

Backend:

```bash
cd Assistant/backend
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8100
```

Frontend:

```bash
cd Assistant/frontend
npm install
npm run dev
```

Set `BACKEND_INTERNAL_URL=http://localhost:8100` for the frontend if needed.
