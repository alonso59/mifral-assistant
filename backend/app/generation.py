from __future__ import annotations

from typing import Any

import httpx

from app.models import GenerationProvider


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


class BaseGenerationProvider:
    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        raise NotImplementedError


class OpenAICompatibleGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, base_url: str | None, api_key: str | None, model_name: str) -> None:
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._api_key = api_key
        self._model_name = model_name

    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model_name,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        response = httpx.post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        return _normalize_openai_content(
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        ).strip()


class AnthropicGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, api_key: str | None, model_name: str) -> None:
        self._api_key = api_key or ""
        self._model_name = model_name

    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        payload = {
            "model": self._model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": messages,
        }
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
            json=payload,
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        parts = [
            item.get("text", "")
            for item in data.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        ]
        return "".join(parts).strip()


class GoogleGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, api_key: str | None, model_name: str) -> None:
        self._api_key = api_key or ""
        self._model_name = model_name

    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        contents = [
            {
                "role": "model" if message["role"] == "assistant" else "user",
                "parts": [{"text": message["content"]}],
            }
            for message in messages
        ]
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model_name}:generateContent",
            params={"key": self._api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": contents,
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()


class OllamaGenerationProvider(BaseGenerationProvider):
    def __init__(self, *, base_url: str | None, model_name: str) -> None:
        self._base_url = (base_url or "http://ollama:11434").rstrip("/")
        self._model_name = model_name

    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = httpx.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model_name,
                "messages": [{"role": "system", "content": system_prompt}, *messages],
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("message", {}).get("content", "")).strip()


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
    return OllamaGenerationProvider(base_url=base_url, model_name=model_name)


def list_ollama_models(base_url: str) -> list[dict[str, Any]]:
    response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=10)
    response.raise_for_status()
    return response.json().get("models", [])
