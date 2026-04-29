from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class ChatLLM(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return one assistant message for the given chat history."""


@dataclass
class OpenAICompatibleLLM:
    """
    Minimal OpenAI-compatible chat client using only the Python standard library.

    Environment fallbacks:
    - `GIS2BEM_LLM_BASE_URL` or `OPENAI_BASE_URL`
    - `GIS2BEM_LLM_API_KEY` or `OPENAI_API_KEY`
    - `GIS2BEM_LLM_MODEL` or `OPENAI_MODEL`
    """

    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    timeout_s: int = 120

    def __post_init__(self) -> None:
        self.model = self.model or os.environ.get("GIS2BEM_LLM_MODEL") or os.environ.get("OPENAI_MODEL")
        self.api_key = self.api_key or os.environ.get("GIS2BEM_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.base_url = (
            self.base_url
            or os.environ.get("GIS2BEM_LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        if not self.model:
            raise ValueError("Missing LLM model. Set GIS2BEM_LLM_MODEL or OPENAI_MODEL.")
        if not self.api_key:
            raise ValueError("Missing LLM API key. Set GIS2BEM_LLM_API_KEY or OPENAI_API_KEY.")

    def complete(self, messages: list[dict[str, str]]) -> str:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


@dataclass
class ScriptedLLM:
    """Deterministic LLM used for tests and smoke checks."""

    responses: list[str]

    def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.responses:
            raise RuntimeError("ScriptedLLM has no remaining responses.")
        return self.responses.pop(0)

