from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

import litellm
from litellm.exceptions import APIConnectionError

from sylvae.backends.base import BackendResult, elapsed_ms
from sylvae.loader import Skill


def _check_model_availability(api_base: str, model: str, timeout: float = 3.0) -> tuple[bool, bool]:
    """Probe Ollama's /api/tags to distinguish "server unreachable" from
    "server reachable but model not pulled" — litellm's own exception
    taxonomy collapses both into the same APIConnectionError, which loses
    the distinction by the time run() would otherwise see it.

    Returns (server_reachable, model_present). model_present is only
    meaningful when server_reachable is True.
    """
    bare_model = model.split("/", 1)[1] if model.startswith("ollama/") else model
    try:
        with urllib.request.urlopen(f"{api_base}/api/tags", timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, OSError, TimeoutError):
        return False, False

    names = {entry.get("name") for entry in data.get("models", [])}
    return True, bare_model in names


class OllamaBackend:
    name = "ollama"

    def __init__(self, model: str = "ollama/qwen2.5:14b", api_base: str = "http://localhost:11434"):
        self.model = model
        self.api_base = api_base

    def run(self, prompt: str, skill: Skill, **kwargs: str) -> BackendResult:
        model = kwargs.get("model", self.model)
        if not model.startswith("ollama/"):
            model = f"ollama/{model}"
        start = time.monotonic()

        reachable, has_model = _check_model_availability(self.api_base, model)
        if not reachable:
            return BackendResult(
                output="", model=model, duration_ms=elapsed_ms(start),
                status="unavailable", error=f"Ollama server unreachable at {self.api_base}",
            )
        if not has_model:
            bare_model = model.split("/", 1)[1] if model.startswith("ollama/") else model
            return BackendResult(
                output="", model=model, duration_ms=elapsed_ms(start),
                status="unavailable",
                error=f"model {bare_model!r} not found on Ollama server — run `ollama pull {bare_model}`",
            )

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
