from __future__ import annotations

import time

import litellm
from litellm.exceptions import APIConnectionError

from sylvae.backends.base import BackendResult, elapsed_ms
from sylvae.loader import Skill


class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str = "ollama/qwen2.5:14b", api_base: str = "http://localhost:11434"):
        self.model = model
        self.api_base = api_base

    def run(self, prompt: str, skill: Skill, **kwargs: object) -> BackendResult:
        model = kwargs.get("model", self.model)
        start = time.monotonic()
        try:
            response = litellm.completion(
                model=model,
                api_base=self.api_base,
                messages=[{"role": "user", "content": prompt}],
            )
        except APIConnectionError as exc:
            return BackendResult(
                output="", model=model, duration_ms=elapsed_ms(start),
                status="unavailable", error=str(exc),
            )
        except Exception as exc:
            return BackendResult(
                output="", model=model, duration_ms=elapsed_ms(start),
                status="failed", error=str(exc),
            )

        output = response["choices"][0]["message"].get("content") or ""
        return BackendResult(output=output, model=model, duration_ms=elapsed_ms(start), status="ok")
