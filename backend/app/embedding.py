from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException

from app.models import EmbeddingProvider


class BaseEmbeddingProvider:
    def embed_one(self, text: str) -> list[float]:
        raise NotImplementedError


class OpenAICompatibleEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, *, base_url: str | None, api_key: str | None, model_name: str) -> None:
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._api_key = api_key
        self._model_name = model_name

    def embed_one(self, text: str) -> list[float]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = httpx.post(
            f"{self._base_url}/embeddings",
            headers=headers,
            json={"model": self._model_name, "input": text},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return list(data.get("data", [{}])[0].get("embedding", []))


class OllamaEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, *, base_url: str | None, model_name: str) -> None:
        self._base_url = (base_url or "http://ollama:11434").rstrip("/")
        self._model_name = model_name

    def embed_one(self, text: str) -> list[float]:
        response = httpx.post(
            f"{self._base_url}/api/embed",
            json={"model": self._model_name, "input": text},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return list(data["embeddings"][0])


class GoogleEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, *, api_key: str | None, model_name: str) -> None:
        self._api_key = api_key or ""
        self._model_name = model_name

    def embed_one(self, text: str) -> list[float]:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model_name}:embedContent",
            params={"key": self._api_key},
            json={"content": {"parts": [{"text": text}]}},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return list(data.get("embedding", {}).get("values", []))


class SentenceTransformersEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(self, *, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any | None = None

    def _get_model(self):  # type: ignore[no-untyped-def]
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "sentence-transformers is not installed in this Assistant runtime. "
                        "Install it to use the local CPU embedding provider."
                    ),
                ) from exc
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def embed_one(self, text: str) -> list[float]:
        vector = self._get_model().encode([text], convert_to_numpy=True)[0]
        return vector.tolist()


def build_embedding_provider(
    provider: EmbeddingProvider,
    *,
    model_name: str,
    api_key: str | None,
    base_url: str | None,
) -> BaseEmbeddingProvider:
    if provider == "openai":
        return OpenAICompatibleEmbeddingProvider(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
        )
    if provider == "google":
        return GoogleEmbeddingProvider(api_key=api_key, model_name=model_name)
    if provider == "sentence-transformers":
        return SentenceTransformersEmbeddingProvider(model_name=model_name)
    return OllamaEmbeddingProvider(base_url=base_url, model_name=model_name)
