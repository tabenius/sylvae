from __future__ import annotations

from anthropic import Anthropic, APIConnectionError

from sylvae.backends.base import BackendResult, elapsed_ms
from sylvae.loader import Skill


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5", api_key: str | None = None):
        self.model = model
        self._client = Anthropic(api_key=api_key)

    def run(self, prompt: str, skill: Skill, **kwargs: str) -> BackendResult:
        import time

        model = kwargs.get("model", self.model)
        start = time.monotonic()
        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=2048,
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

        output = "".join(block.text for block in response.content if block.type == "text")
        return BackendResult(output=output, model=model, duration_ms=elapsed_ms(start), status="ok")
