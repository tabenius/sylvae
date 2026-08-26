from __future__ import annotations

from anthropic import (
    Anthropic,
    APIConnectionError,
    AuthenticationError,
    PermissionDeniedError,
)

from sylvae.backends.base import DEFAULT_BACKEND_TIMEOUT, BackendResult, elapsed_ms
from sylvae.loader import Skill


class AnthropicBackend:
    name = "anthropic"

    def __init__(
        self,
        model: str = "claude-sonnet-5",
        api_key: str | None = None,
        timeout: float = DEFAULT_BACKEND_TIMEOUT,
    ):
        self.model = model
        self.timeout = timeout
        self._client = Anthropic(api_key=api_key)

    def run(self, prompt: str, skill: Skill, **kwargs: str) -> BackendResult:
        import time

        model = kwargs.get("model", self.model)
        start = time.monotonic()

        # No credentials is a CONFIGURATION problem, not a quality one. It
        # used to fall through to the generic handler and be recorded as
        # 'failed', which would tell adaptive routing that this backend runs
        # and answers badly -- when in fact it never ran at all. Checked up
        # front, mirroring the Ollama backend's availability preflight.
        if not getattr(self._client, "api_key", None) and not getattr(
            self._client, "auth_token", None
        ):
            return BackendResult(
                output="", model=model, duration_ms=elapsed_ms(start),
                status="unavailable",
                error=(
                    "no Anthropic credentials configured (set ANTHROPIC_API_KEY). "
                    "Note an API key is a separate paid product from a Claude "
                    "subscription; the claudecode backend uses the latter."
                ),
            )

        try:
            response = self._client.messages.create(
                model=model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
                timeout=self.timeout,
            )
        except (AuthenticationError, PermissionDeniedError) as exc:
            # Credentials present but rejected: still 'never ran', not 'ran badly'.
            return BackendResult(
                output="", model=model, duration_ms=elapsed_ms(start),
                status="unavailable", error=f"Anthropic rejected the credentials: {exc}",
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
