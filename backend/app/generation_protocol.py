from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass(frozen=True)
class GenerationEvent:
    kind: Literal["token", "thinking", "thinking_text"]
    token: str | None = None
    value: bool | None = None
    text: str | None = None


@runtime_checkable
class GenerationProvider(Protocol):
    supports_reasoning: bool

    def stream(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[str, None, None]: ...

    def stream_events(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[GenerationEvent, None, None]: ...

    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str: ...


class BaseGenerationProvider:
    supports_reasoning = False

    def generate(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> str:
        return "".join(
            self.stream(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        ).strip()

    def stream_events(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[GenerationEvent, None, None]:
        for token in self.stream(
            system_prompt=system_prompt,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield GenerationEvent(kind="token", token=token)
