from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from sylvae.loader import Skill


@dataclass(frozen=True)
class BackendResult:
    output: str
    model: str
    duration_ms: int
    status: str  # "ok" | "failed" | "unavailable"
    error: str | None = None


class Backend(Protocol):
    name: str

    def run(self, prompt: str, skill: Skill, **kwargs: object) -> BackendResult: ...


def elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
