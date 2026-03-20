from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import HTTPException

from app.generation_protocol import BaseGenerationProvider, GenerationEvent
from app.models import GenerationProvider

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"


def normalize_ollama_base_url(base_url: str | None) -> str:
    raw = (base_url or "http://localhost:11434").strip()
    if not raw:
        raw = "http://localhost:11434"
    parsed = urlsplit(raw)
    if not parsed.scheme:
        raw = f"http://{raw.lstrip('/')}"
        parsed = urlsplit(raw)

    host = (parsed.hostname or "").lower()
    port = parsed.port
    scheme = parsed.scheme.lower()
    running_in_docker = os.getenv("RUNNING_IN_DOCKER", "").lower() in {"1", "true", "yes", "on"}
    if running_in_docker and host in {"localhost", "127.0.0.1", "::1"}:
        docker_host = os.getenv("OLLAMA_DOCKER_HOST", "host.docker.internal")
        parsed = parsed._replace(netloc=f"{docker_host}:{port or 11434}")
        raw = urlunsplit(parsed)
        host = docker_host
    should_force_http = scheme == "https" and (
        port == 11434
        or host in {"ollama", "localhost", "127.0.0.1", "host.docker.internal"}
    )
    if should_force_http:
        parsed = parsed._replace(scheme="http")
        raw = urlunsplit(parsed)

    return raw.rstrip("/")


def _normalize_openai_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


def _headers(api_key: str | None) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _iter_sse_json(response: httpx.Response):
    for line in response.iter_lines():
        if not line or line.startswith("event:"):
            continue
        raw = line[6:] if line.startswith("data: ") else line
        if raw.strip() == "[DONE]":
            break
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


def _sanitize_reasoning_summary(text: str) -> str:
    collapsed = " ".join(text.split()).strip()
    if not collapsed:
        return ""
    return collapsed[:157] + "..." if len(collapsed) > 160 else collapsed


def _extract_reasoning_summary(reasoning_details: Any) -> str | None:
    if not isinstance(reasoning_details, list):
        return None
    summaries: list[str] = []
    for detail in reasoning_details:
        if not isinstance(detail, dict):
            continue
        if detail.get("type") != "reasoning.summary":
            continue
        summary = _sanitize_reasoning_summary(str(detail.get("summary") or ""))
        if summary:
            summaries.append(summary)
    return summaries[-1] if summaries else None


class OpenAICompatibleGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, base_url: str | None, api_key: str | None, model_name: str) -> None:
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._api_key = api_key
        self._model_name = model_name

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ):
        payload = {
            "model": self._model_name,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        with httpx.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            headers=_headers(self._api_key),
            json=payload,
            timeout=120,
        ) as response:
            response.raise_for_status()
            for data in _iter_sse_json(response):
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                token = delta.get("content")
                if token:
                    yield str(token)


class AnthropicGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, api_key: str | None, model_name: str) -> None:
        self._api_key = api_key or ""
        self._model_name = model_name

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ):
        payload = {
            "model": self._model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": messages,
            "stream": True,
        }
        with httpx.stream(
            "POST",
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Accept": "text/event-stream",
            },
            json=payload,
            timeout=120,
        ) as response:
            response.raise_for_status()
            for data in _iter_sse_json(response):
                if data.get("type") != "content_block_delta":
                    continue
                delta = data.get("delta") or {}
                token = delta.get("text")
                if token:
                    yield str(token)


class GoogleGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, api_key: str | None, model_name: str) -> None:
        self._api_key = api_key or ""
        self._model_name = model_name

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ):
        contents = [
            {
                "role": "model" if message["role"] == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            }
            for message in messages
        ]
        with httpx.stream(
            "POST",
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model_name}:streamGenerateContent",
            params={"key": self._api_key, "alt": "sse"},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=120,
        ) as response:
            response.raise_for_status()
            for data in _iter_sse_json(response):
                candidates = data.get("candidates", [])
                if not candidates:
                    continue
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    if isinstance(part, dict) and part.get("text"):
                        yield str(part["text"])


class OllamaGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, base_url: str | None, model_name: str) -> None:
        self._base_url = normalize_ollama_base_url(base_url)
        self._model_name = model_name

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ):
        with httpx.stream(
            "POST",
            f"{self._base_url}/api/chat",
            json={
                "model": self._model_name,
                "messages": [{"role": "system", "content": system_prompt}, *messages],
                "stream": True,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            },
            timeout=120,
        ) as response:
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = None
                try:
                    detail = exc.response.json().get("error")
                except Exception:
                    detail = exc.response.text.strip() or None
                if exc.response.status_code == 404 and detail:
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "Ollama could not serve the selected model. "
                            "Pull it from Settings first."
                        ),
                    ) from exc
                raise HTTPException(
                    status_code=503,
                    detail=f"Ollama generation failed: {detail or exc.response.reason_phrase}",
                ) from exc
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = data.get("message", {}).get("content")
                if token:
                    yield str(token)


def _openrouter_model_name(entry: dict[str, Any]) -> str:
    return str(entry.get("id") or entry.get("name") or "")


def _openrouter_supports_reasoning(entry: dict[str, Any]) -> bool:
    params = entry.get("supported_parameters") or []
    if not isinstance(params, list):
        return False
    return "reasoning" in params or "include_reasoning" in params


def list_openrouter_models(*, api_key: str, base_url: str | None = None) -> list[dict[str, Any]]:
    response = httpx.get(
        f"{(base_url or OPENROUTER_BASE_URL).rstrip('/')}/models",
        headers=_headers(api_key),
        timeout=15,
    )
    response.raise_for_status()
    body = response.json()
    data = body.get("data") or body.get("models") or []
    return data if isinstance(data, list) else []


@lru_cache(maxsize=128)
def openrouter_model_supports_reasoning(*, api_key: str, model_name: str, base_url: str | None = None) -> bool:
    try:
        models = list_openrouter_models(api_key=api_key, base_url=base_url)
    except Exception:
        return False
    for entry in models:
        if _openrouter_model_name(entry) == model_name:
            return _openrouter_supports_reasoning(entry)
    return False


class OpenRouterGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, api_key: str | None, model_name: str, base_url: str | None) -> None:
        self._api_key = api_key or ""
        self._model_name = model_name
        self._base_url = (base_url or OPENROUTER_BASE_URL).rstrip("/")
        self._supports_reasoning: bool | None = None

    @property
    def supports_reasoning(self) -> bool:
        if self._supports_reasoning is None:
            self._supports_reasoning = openrouter_model_supports_reasoning(
                api_key=self._api_key,
                model_name=self._model_name,
                base_url=self._base_url,
            )
        return self._supports_reasoning

    def stream_events(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ):
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if self.supports_reasoning:
            payload["reasoning"] = {"enabled": True}

        thinking_active = False
        last_summary: str | None = None
        with httpx.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            headers=_headers(self._api_key),
            json=payload,
            timeout=120,
        ) as response:
            response.raise_for_status()
            if self.supports_reasoning:
                thinking_active = True
                yield GenerationEvent(kind="thinking", value=True)
            for data in _iter_sse_json(response):
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                summary = _extract_reasoning_summary(delta.get("reasoning_details"))
                if summary and summary != last_summary:
                    last_summary = summary
                    yield GenerationEvent(kind="thinking_text", text=summary)
                token = delta.get("content")
                if token:
                    if thinking_active:
                        thinking_active = False
                        yield GenerationEvent(kind="thinking", value=False)
                    yield GenerationEvent(kind="token", token=str(token))
            if thinking_active:
                yield GenerationEvent(kind="thinking", value=False)

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ):
        for event in self.stream_events(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            if event.kind == "token" and event.token:
                yield event.token


def build_generation_provider(
    provider: GenerationProvider,
    *,
    model_name: str,
    api_key: str | None,
    base_url: str | None,
) -> BaseGenerationProvider:
    if provider == "openai":
        return OpenAICompatibleGenerationProvider(
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
        )
    if provider == "anthropic":
        return AnthropicGenerationProvider(api_key=api_key, model_name=model_name)
    if provider == "google":
        return GoogleGenerationProvider(api_key=api_key, model_name=model_name)
    if provider == "openrouter":
        return OpenRouterGenerationProvider(
            api_key=api_key,
            model_name=model_name,
            base_url=base_url,
        )
    return OllamaGenerationProvider(base_url=base_url, model_name=model_name)


def list_ollama_models(base_url: str) -> list[dict[str, Any]]:
    normalized = normalize_ollama_base_url(base_url)
    if "openrouter.ai" in normalized:
        raise HTTPException(
            status_code=400,
            detail="Ollama model listing requires an Ollama base URL, not an OpenRouter URL.",
        )
    response = httpx.get(f"{normalized}/api/tags", timeout=10)
    response.raise_for_status()
    return response.json().get("models", [])


def check_ollama_health(base_url: str) -> dict[str, Any]:
    normalized = normalize_ollama_base_url(base_url)
    if "openrouter.ai" in normalized:
        raise HTTPException(
            status_code=400,
            detail="Ollama health checks require an Ollama base URL, not an OpenRouter URL.",
        )
    response = httpx.get(f"{normalized}/api/tags", timeout=10)
    response.raise_for_status()
    payload = response.json()
    return {
        "ok": True,
        "model_count": len(payload.get("models", [])),
    }


def pull_ollama_model(base_url: str, model: str):
    normalized = normalize_ollama_base_url(base_url)
    if "openrouter.ai" in normalized:
        raise HTTPException(
            status_code=400,
            detail="Ollama model pull requires an Ollama base URL, not an OpenRouter URL.",
        )
    with httpx.stream(
        "POST",
        f"{normalized}/api/pull",
        json={"name": model, "stream": True},
        timeout=None,
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            yield line
