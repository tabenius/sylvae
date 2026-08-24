from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Protocol

from sylvae.loader import Skill


class InvalidModelName(ValueError):
    """Raised when a model identifier could be mistaken for a CLI flag."""


# Real model ids across all backends: claude-sonnet-5, ollama/mistral:latest,
# opencode/big-pickle, gpt-5.6-sol, mistral:7b-instruct-q4_0. All are word
# characters plus / : . - and must begin alphanumeric.
_SAFE_MODEL = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:/-]*\Z")


def validate_model_name(model: str) -> str:
    """Reject model identifiers that are shaped like command-line flags.

    Three of the five backends pass the model through to a CLI as argv
    (codex -m, opencode --model, claude --model). A value beginning with a
    dash lands next to that flag as a token the downstream parser may read
    as a flag in its own right -- and the candidates are not harmless:
    --dangerously-bypass-approvals-and-sandbox is a real codex flag that
    disables its sandbox.

    Whether a given parser treats such a token as a value or an option is
    version-dependent behaviour of somebody else's argument parser. That is
    not a thing to depend on for a security property, so the value is
    refused here instead, before any process is spawned.

    Shell metacharacters are refused for a different reason: they are not
    exploitable today, because every backend builds argv as a list and none
    of them ever goes through a shell. But a model id containing them is
    malformed under any reading, and refusing them now means a future
    backend that does build a command string cannot reintroduce the
    question.
    """
    if not isinstance(model, str) or not _SAFE_MODEL.match(model):
        raise InvalidModelName(
            f"invalid model identifier {model!r}: must begin with an alphanumeric "
            "character and contain only [A-Za-z0-9._:/-]"
        )
    return model


@dataclass(frozen=True)
class BackendResult:
    output: str
    model: str
    duration_ms: int
    status: str  # "ok" | "failed" | "unavailable"
    error: str | None = None


class Backend(Protocol):
    name: str

    def run(self, prompt: str, skill: Skill, **kwargs: str) -> BackendResult: ...


def elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
