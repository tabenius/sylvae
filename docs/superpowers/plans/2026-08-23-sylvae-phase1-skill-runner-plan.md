# Sylvae Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a portable skill runner that loads a `SKILL.md`-format skill, dispatches it to one of three backends (Anthropic API, local Ollama, or a stubbed shellout backend), and records what happened — proving the full loop end to end against real skills.

**Architecture:** A small Python package (`sylvae`) with four independent, individually-tested pieces — a skill loader, a set of backend adapters behind one shared interface, a runner that wires loader → backend → evidence log, and a thin CLI. No routing, no GUI, no WeftMark dependency.

**Tech Stack:** Python 3.11+, `anthropic` SDK (direct), `litellm` (Ollama connector), `pytest`, `argparse` (stdlib CLI).

**Spec:** `docs/superpowers/specs/2026-08-21-sylvae-phase1-skill-runner-design.md`

## Global Constraints

- Python 3.11+ — matches WeftMark's own stack.
- Standalone experiment: no runtime import of, or dependency on, WeftMark code.
- Evidence status is exactly one of `ok`, `failed`, `unavailable` — a backend that's unreachable is `unavailable`, never `failed`.
- Fails closed: never silently substitute a different backend than the one requested.
- Reuse the existing `SKILL.md` format (YAML frontmatter + Markdown body) — do not invent a new skill format.
- Backend selection is a required manual CLI flag in phase 1 — no automatic routing/classification.
- Evidence record field names are WeftMark-shaped (`status: ok|failed|unavailable`, actor/backend/model provenance) but Sylvae takes no runtime dependency on WeftMark.
- Out of scope for phase 1: automatic routing, any GUI, the semantic-definitions thread, the memory-unification thread, wiring evidence into WeftMark.

---

## File Structure

```
Sylvae/
  pyproject.toml
  .gitignore
  README.md
  src/sylvae/
    __init__.py
    loader.py            # Skill dataclass, load_skill(), SkillLoadError
    backends/
      __init__.py
      base.py             # BackendResult, Backend protocol, elapsed_ms()
      anthropic_backend.py
      ollama_backend.py
      shellout_backend.py
    evidence.py           # EvidenceRecord, append_evidence()
    runner.py             # resolve_input(), build_prompt(), run_skill(), BACKENDS
    cli.py                # main() — argparse entrypoint, console_script "sylvae"
  skills/
    summarize-diff/SKILL.md
    disk-report/SKILL.md
  tests/
    test_loader.py
    test_anthropic_backend.py
    test_ollama_backend.py
    test_shellout_backend.py
    test_evidence.py
    test_runner.py
    test_cli.py
  runs/                    # created at runtime, gitignored
```

`skills/` holds the real, usable skill definitions — tests read directly from this directory rather than duplicating fixtures elsewhere (DRY).

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `README.md`
- Create: `src/sylvae/__init__.py`
- Create: `src/sylvae/backends/__init__.py`

**Interfaces:**
- Produces: an installable `sylvae` package (`pip install -e ".[dev]"` works), the `src/sylvae/` and `src/sylvae/backends/` packages later tasks add modules to.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "sylvae"
version = "0.1.0"
description = "A portable skill runner across agent backends."
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40",
    "litellm>=1.50",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
sylvae = "sylvae.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/sylvae"]
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
runs/
*.egg-info/
.pytest_cache/
```

- [ ] **Step 3: Write `README.md`**

```markdown
# Sylvae

A portable skill runner: load a `SKILL.md`-format skill and run it against
Anthropic's API, a local Ollama model, or (stubbed for now) a CLI-only
harness — with every run logged as a durable evidence record.

Phase 1 goal, architecture, and rationale: see
`docs/superpowers/specs/2026-08-21-sylvae-phase1-skill-runner-design.md`.

## Setup

    python -m venv .venv
    . .venv/bin/activate
    pip install -e ".[dev]"

## Run

    sylvae run skills/summarize-diff --backend anthropic --input path/to/diff.txt

## Test

    pytest
```

- [ ] **Step 4: Create package skeleton**

```bash
mkdir -p src/sylvae/backends
touch src/sylvae/__init__.py
touch src/sylvae/backends/__init__.py
mkdir -p tests skills runs
```

- [ ] **Step 5: Install and verify**

Run:
```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
python -c "import sylvae; print('ok')"
pytest --collect-only
```
Expected: prints `ok`; pytest collects zero tests without error.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore README.md src/ tests/ skills/
git commit -m "Scaffold Sylvae package"
```

---

### Task 2: Skill loader

**Files:**
- Create: `src/sylvae/loader.py`
- Test: `tests/test_loader.py`
- Create (fixture, used by this task's test): `skills/summarize-diff/SKILL.md` (full content in Task 9 — a minimal stand-in is created here and overwritten with real content in Task 9)

**Interfaces:**
- Produces: `Skill` dataclass (`slug: str`, `name: str`, `description: str`, `instructions: str`, `path: Path`), `load_skill(skill_dir: str | Path) -> Skill`, `SkillLoadError(Exception)`. Every later task that touches a skill imports these from `sylvae.loader`.

- [ ] **Step 1: Write the failing test**

`tests/test_loader.py`:
```python
from pathlib import Path

import pytest

from sylvae.loader import Skill, SkillLoadError, load_skill

FIXTURE = Path(__file__).parent.parent / "skills" / "summarize-diff"


def test_load_skill_parses_frontmatter_and_body():
    skill = load_skill(FIXTURE)

    assert isinstance(skill, Skill)
    assert skill.slug == "summarize-diff"
    assert skill.name == "summarize-diff"
    assert "diff" in skill.description.lower()
    assert len(skill.instructions.strip()) > 0
    assert skill.path == FIXTURE


def test_load_skill_missing_directory_raises():
    with pytest.raises(SkillLoadError):
        load_skill(Path(__file__).parent / "does-not-exist")


def test_load_skill_missing_frontmatter_raises(tmp_path):
    bad = tmp_path / "bad-skill"
    bad.mkdir()
    (bad / "SKILL.md").write_text("no frontmatter here")

    with pytest.raises(SkillLoadError):
        load_skill(bad)
```

- [ ] **Step 2: Create the fixture skill (minimal, real content)**

`skills/summarize-diff/SKILL.md`:
```markdown
---
name: summarize-diff
description: Summarize a git diff into a short, plain-language description of what changed.
---

Summarize the given diff in plain language.
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_loader.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sylvae.loader'`

- [ ] **Step 4: Write minimal implementation**

`src/sylvae/loader.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


class SkillLoadError(Exception):
    pass


@dataclass(frozen=True)
class Skill:
    slug: str
    name: str
    description: str
    instructions: str
    path: Path


def load_skill(skill_dir: str | Path) -> Skill:
    path = Path(skill_dir)
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        raise SkillLoadError(f"no SKILL.md found in {path}")

    raw = skill_file.read_text()
    if not raw.startswith("---"):
        raise SkillLoadError(f"{skill_file} is missing YAML frontmatter")

    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise SkillLoadError(f"{skill_file} has malformed frontmatter")

    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise SkillLoadError(f"{skill_file} has invalid YAML frontmatter: {exc}") from exc

    for key in ("name", "description"):
        if key not in meta:
            raise SkillLoadError(f"{skill_file} frontmatter is missing required key '{key}'")

    return Skill(
        slug=path.name,
        name=meta["name"],
        description=meta["description"],
        instructions=parts[2].strip(),
        path=path,
    )
```

Add `pyyaml>=6.0` to `pyproject.toml`'s `dependencies` list and re-run `pip install -e ".[dev]"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_loader.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/sylvae/loader.py tests/test_loader.py skills/summarize-diff/SKILL.md pyproject.toml
git commit -m "Add SKILL.md loader"
```

---

### Task 3: Backend interface + Anthropic backend

**Files:**
- Create: `src/sylvae/backends/base.py`
- Create: `src/sylvae/backends/anthropic_backend.py`
- Test: `tests/test_anthropic_backend.py`

**Interfaces:**
- Consumes: `Skill` from `sylvae.loader` (Task 2).
- Produces: `BackendResult` dataclass (`output: str`, `model: str`, `duration_ms: int`, `status: str`, `error: str | None = None`), `elapsed_ms(start: float) -> int`, both in `sylvae.backends.base`. `AnthropicBackend(model: str = "claude-sonnet-5", api_key: str | None = None)` with attribute `name = "anthropic"` and method `run(self, prompt: str, skill: Skill) -> BackendResult`, in `sylvae.backends.anthropic_backend`. Later tasks (Ollama, Shellout, Runner) reuse `BackendResult` and `elapsed_ms` from `base.py`.

- [ ] **Step 1: Write the failing test**

`tests/test_anthropic_backend.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from anthropic import APIConnectionError

from sylvae.backends.anthropic_backend import AnthropicBackend
from sylvae.loader import Skill


def make_skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))


@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_run_returns_ok_on_success(mock_anthropic_cls):
    mock_block = MagicMock(type="text", text="hello there")
    mock_response = MagicMock(content=[mock_block])
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_anthropic_cls.return_value = mock_client

    backend = AnthropicBackend(api_key="fake")
    result = backend.run("prompt", make_skill())

    assert result.status == "ok"
    assert result.output == "hello there"
    assert result.model == "claude-sonnet-5"


@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_run_returns_unavailable_on_connection_error(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = APIConnectionError(
        message="boom", request=httpx.Request("POST", "https://api.anthropic.com")
    )
    mock_anthropic_cls.return_value = mock_client

    backend = AnthropicBackend(api_key="fake")
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"


@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_run_returns_failed_on_other_errors(mock_anthropic_cls):
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = RuntimeError("something else broke")
    mock_anthropic_cls.return_value = mock_client

    backend = AnthropicBackend(api_key="fake")
    result = backend.run("prompt", make_skill())

    assert result.status == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_anthropic_backend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sylvae.backends.anthropic_backend'`

If `APIConnectionError(message=..., request=...)` raises a `TypeError` about unexpected keyword arguments once the module exists, check the installed SDK's actual signature with `python -c "import inspect, anthropic; print(inspect.signature(anthropic.APIConnectionError.__init__))"` and adjust the test call to match.

- [ ] **Step 3: Write minimal implementation**

`src/sylvae/backends/base.py`:
```python
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

    def run(self, prompt: str, skill: Skill) -> BackendResult: ...


def elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)
```

`src/sylvae/backends/anthropic_backend.py`:
```python
from __future__ import annotations

from anthropic import Anthropic, APIConnectionError

from sylvae.backends.base import BackendResult, elapsed_ms
from sylvae.loader import Skill


class AnthropicBackend:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5", api_key: str | None = None):
        self.model = model
        self._client = Anthropic(api_key=api_key)

    def run(self, prompt: str, skill: Skill) -> BackendResult:
        import time

        start = time.monotonic()
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
        except APIConnectionError as exc:
            return BackendResult(
                output="", model=self.model, duration_ms=elapsed_ms(start),
                status="unavailable", error=str(exc),
            )
        except Exception as exc:
            return BackendResult(
                output="", model=self.model, duration_ms=elapsed_ms(start),
                status="failed", error=str(exc),
            )

        output = "".join(block.text for block in response.content if block.type == "text")
        return BackendResult(output=output, model=self.model, duration_ms=elapsed_ms(start), status="ok")
```

Add `httpx` is already a transitive dependency of `anthropic`; no extra dependency needed for the test import.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_anthropic_backend.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/sylvae/backends/base.py src/sylvae/backends/anthropic_backend.py tests/test_anthropic_backend.py
git commit -m "Add backend interface and Anthropic backend"
```

---

### Task 4: Ollama backend

**Files:**
- Create: `src/sylvae/backends/ollama_backend.py`
- Test: `tests/test_ollama_backend.py`

**Interfaces:**
- Consumes: `BackendResult`, `elapsed_ms` from `sylvae.backends.base` (Task 3); `Skill` from `sylvae.loader` (Task 2).
- Produces: `OllamaBackend(model: str = "ollama/qwen2.5:14b", api_base: str = "http://localhost:11434")`, attribute `name = "ollama"`, method `run(self, prompt: str, skill: Skill) -> BackendResult`, in `sylvae.backends.ollama_backend`. Consumed by Runner (Task 7).

- [ ] **Step 1: Write the failing test**

`tests/test_ollama_backend.py`:
```python
from pathlib import Path
from unittest.mock import patch

from litellm.exceptions import APIConnectionError

from sylvae.backends.ollama_backend import OllamaBackend
from sylvae.loader import Skill


def make_skill() -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))


@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_ok_on_success(mock_completion):
    mock_completion.return_value = {
        "choices": [{"message": {"content": "the local answer"}}]
    }

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "ok"
    assert result.output == "the local answer"
    assert result.model == "ollama/qwen2.5:14b"


@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_unavailable_when_ollama_unreachable(mock_completion):
    mock_completion.side_effect = APIConnectionError(
        message="connection refused", llm_provider="ollama", model="qwen2.5:14b"
    )

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "unavailable"


@patch("sylvae.backends.ollama_backend.litellm.completion")
def test_run_returns_failed_on_other_errors(mock_completion):
    mock_completion.side_effect = RuntimeError("something else broke")

    backend = OllamaBackend()
    result = backend.run("prompt", make_skill())

    assert result.status == "failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ollama_backend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sylvae.backends.ollama_backend'`

If `APIConnectionError(message=..., llm_provider=..., model=...)` raises a `TypeError`, check the installed version with `python -c "import inspect, litellm.exceptions; print(inspect.signature(litellm.exceptions.APIConnectionError.__init__))"` and adjust.

- [ ] **Step 3: Write minimal implementation**

`src/sylvae/backends/ollama_backend.py`:
```python
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

    def run(self, prompt: str, skill: Skill) -> BackendResult:
        start = time.monotonic()
        try:
            response = litellm.completion(
                model=self.model,
                api_base=self.api_base,
                messages=[{"role": "user", "content": prompt}],
            )
        except APIConnectionError as exc:
            return BackendResult(
                output="", model=self.model, duration_ms=elapsed_ms(start),
                status="unavailable", error=str(exc),
            )
        except Exception as exc:
            return BackendResult(
                output="", model=self.model, duration_ms=elapsed_ms(start),
                status="failed", error=str(exc),
            )

        output = response["choices"][0]["message"]["content"]
        return BackendResult(output=output, model=self.model, duration_ms=elapsed_ms(start), status="ok")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ollama_backend.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/sylvae/backends/ollama_backend.py tests/test_ollama_backend.py
git commit -m "Add Ollama backend"
```

---

### Task 5: Shellout backend (stub)

**Files:**
- Create: `src/sylvae/backends/shellout_backend.py`
- Test: `tests/test_shellout_backend.py`

**Interfaces:**
- Consumes: `BackendResult` from `sylvae.backends.base` (Task 3); `Skill` from `sylvae.loader` (Task 2).
- Produces: `ShelloutBackend(command: str = "codex")`, attribute `name = "shellout"`, method `run(self, prompt: str, skill: Skill) -> BackendResult` — always returns `status="unavailable"` in phase 1. Consumed by Runner (Task 7) so all three backends are registered even though this one isn't functional yet.

- [ ] **Step 1: Write the failing test**

`tests/test_shellout_backend.py`:
```python
from pathlib import Path

from sylvae.backends.shellout_backend import ShelloutBackend
from sylvae.loader import Skill


def test_run_is_unavailable_in_phase_one():
    skill = Skill(slug="s", name="s", description="d", instructions="do X", path=Path("."))
    backend = ShelloutBackend()

    result = backend.run("prompt", skill)

    assert result.status == "unavailable"
    assert backend.name == "shellout"
    assert "not implemented" in (result.error or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_shellout_backend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sylvae.backends.shellout_backend'`

- [ ] **Step 3: Write minimal implementation**

`src/sylvae/backends/shellout_backend.py`:
```python
from __future__ import annotations

from sylvae.backends.base import BackendResult
from sylvae.loader import Skill


class ShelloutBackend:
    """Runs a CLI-only harness (Codex, OpenCode) as a subprocess.

    Not implemented in phase 1 — see the open question in the phase-1
    spec. The interface is wired up now so the runner and CLI don't need
    changes when a real implementation lands.
    """

    name = "shellout"

    def __init__(self, command: str = "codex"):
        self.command = command

    def run(self, prompt: str, skill: Skill) -> BackendResult:
        return BackendResult(
            output="",
            model=self.command,
            duration_ms=0,
            status="unavailable",
            error="shellout backend not implemented in phase 1",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_shellout_backend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sylvae/backends/shellout_backend.py tests/test_shellout_backend.py
git commit -m "Add shellout backend stub"
```

---

### Task 6: Evidence record

**Files:**
- Create: `src/sylvae/evidence.py`
- Test: `tests/test_evidence.py`

**Interfaces:**
- Produces: `EvidenceRecord` dataclass (`skill: str`, `backend: str`, `model: str`, `input_summary: str`, `output: str`, `duration_ms: int`, `status: str`, `timestamp: str`), `append_evidence(record: EvidenceRecord, runs_dir: str | Path = "runs") -> Path`, in `sylvae.evidence`. Consumed by Runner (Task 7).

- [ ] **Step 1: Write the failing test**

`tests/test_evidence.py`:
```python
import json

from sylvae.evidence import EvidenceRecord, append_evidence


def make_record(timestamp: str = "2026-08-23T10:00:00+00:00") -> EvidenceRecord:
    return EvidenceRecord(
        skill="summarize-diff",
        backend="ollama",
        model="ollama/qwen2.5:14b",
        input_summary="diff --git a/x b/x",
        output="Changed x.",
        duration_ms=1234,
        status="ok",
        timestamp=timestamp,
    )


def test_append_evidence_writes_one_json_line(tmp_path):
    runs_dir = tmp_path / "runs"
    record = make_record()

    written_path = append_evidence(record, runs_dir=runs_dir)

    assert written_path == runs_dir / "2026-08-23.jsonl"
    lines = written_path.read_text().strip().splitlines()
    assert len(lines) == 1
    loaded = json.loads(lines[0])
    assert loaded["skill"] == "summarize-diff"
    assert loaded["status"] == "ok"


def test_append_evidence_appends_to_same_day_file(tmp_path):
    runs_dir = tmp_path / "runs"
    append_evidence(make_record(), runs_dir=runs_dir)
    append_evidence(make_record(), runs_dir=runs_dir)

    lines = (runs_dir / "2026-08-23.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evidence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sylvae.evidence'`

- [ ] **Step 3: Write minimal implementation**

`src/sylvae/evidence.py`:
```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvidenceRecord:
    skill: str
    backend: str
    model: str
    input_summary: str
    output: str
    duration_ms: int
    status: str  # "ok" | "failed" | "unavailable"
    timestamp: str  # ISO 8601


def append_evidence(record: EvidenceRecord, runs_dir: str | Path = "runs") -> Path:
    runs_path = Path(runs_dir)
    runs_path.mkdir(parents=True, exist_ok=True)

    date_part = record.timestamp[:10]
    out_file = runs_path / f"{date_part}.jsonl"

    with out_file.open("a") as f:
        f.write(json.dumps(asdict(record)) + "\n")

    return out_file
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evidence.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/sylvae/evidence.py tests/test_evidence.py
git commit -m "Add evidence record logging"
```

---

### Task 7: Runner

**Files:**
- Create: `src/sylvae/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `load_skill`, `Skill`, `SkillLoadError` from `sylvae.loader` (Task 2); `BackendResult` from `sylvae.backends.base` (Task 3); `AnthropicBackend` (Task 3), `OllamaBackend` (Task 4), `ShelloutBackend` (Task 5); `EvidenceRecord`, `append_evidence` from `sylvae.evidence` (Task 6).
- Produces: `BACKENDS: dict[str, type]` (keys `"anthropic"`, `"ollama"`, `"shellout"`), `resolve_input(raw: str) -> str`, `build_prompt(skill: Skill, resolved_input: str) -> str`, `run_skill(skill_path: str | Path, backend_name: str, raw_input: str, runs_dir: str | Path = "runs") -> EvidenceRecord`, in `sylvae.runner`. Consumed by CLI (Task 8).

- [ ] **Step 1: Write the failing test**

`tests/test_runner.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sylvae.backends.base import BackendResult
from sylvae.runner import BACKENDS, build_prompt, resolve_input, run_skill
from sylvae.loader import Skill

SKILL_PATH = Path(__file__).parent.parent / "skills" / "summarize-diff"


def test_resolve_input_reads_existing_file(tmp_path):
    f = tmp_path / "diff.txt"
    f.write_text("diff --git a/x b/x")

    assert resolve_input(str(f)) == "diff --git a/x b/x"


def test_resolve_input_passes_through_literal_text():
    assert resolve_input("just some text") == "just some text"


def test_build_prompt_includes_skill_instructions_and_input():
    skill = Skill(slug="s", name="s", description="d", instructions="Summarize it.", path=Path("."))

    prompt = build_prompt(skill, "the diff content")

    assert "Summarize it." in prompt
    assert "the diff content" in prompt


def test_run_skill_writes_evidence_and_returns_record(tmp_path, monkeypatch):
    fake_backend = MagicMock()
    fake_backend.run.return_value = BackendResult(
        output="a summary", model="fake-model", duration_ms=10, status="ok"
    )
    monkeypatch.setitem(BACKENDS, "fake", MagicMock(return_value=fake_backend))

    record = run_skill(SKILL_PATH, "fake", "some input text", runs_dir=tmp_path)

    assert record.status == "ok"
    assert record.output == "a summary"
    assert record.skill == "summarize-diff"
    assert (tmp_path / f"{record.timestamp[:10]}.jsonl").exists()


def test_run_skill_rejects_unknown_backend(tmp_path):
    with pytest.raises(ValueError):
        run_skill(SKILL_PATH, "not-a-real-backend", "input", runs_dir=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sylvae.runner'`

- [ ] **Step 3: Write minimal implementation**

`src/sylvae/runner.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sylvae.backends.anthropic_backend import AnthropicBackend
from sylvae.backends.ollama_backend import OllamaBackend
from sylvae.backends.shellout_backend import ShelloutBackend
from sylvae.evidence import EvidenceRecord, append_evidence
from sylvae.loader import Skill, load_skill

BACKENDS = {
    "anthropic": AnthropicBackend,
    "ollama": OllamaBackend,
    "shellout": ShelloutBackend,
}


def resolve_input(raw: str) -> str:
    path = Path(raw)
    if path.is_file():
        return path.read_text()
    return raw


def build_prompt(skill: Skill, resolved_input: str) -> str:
    return f"{skill.instructions}\n\n---\n\nTask input:\n{resolved_input}"


def run_skill(
    skill_path: str | Path,
    backend_name: str,
    raw_input: str,
    runs_dir: str | Path = "runs",
) -> EvidenceRecord:
    if backend_name not in BACKENDS:
        raise ValueError(f"unknown backend: {backend_name!r} (known: {sorted(BACKENDS)})")

    skill = load_skill(skill_path)
    resolved_input = resolve_input(raw_input)
    prompt = build_prompt(skill, resolved_input)

    backend = BACKENDS[backend_name]()
    result = backend.run(prompt, skill)

    record = EvidenceRecord(
        skill=skill.slug,
        backend=backend_name,
        model=result.model,
        input_summary=resolved_input[:200],
        output=result.output,
        duration_ms=result.duration_ms,
        status=result.status,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    append_evidence(record, runs_dir=runs_dir)
    return record
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_runner.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/sylvae/runner.py tests/test_runner.py
git commit -m "Add runner: loader + backend + evidence orchestration"
```

---

### Task 8: CLI

**Files:**
- Create: `src/sylvae/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `BACKENDS`, `run_skill` from `sylvae.runner` (Task 7).
- Produces: `main(argv: list[str] | None = None) -> int`, registered as the `sylvae` console script (via `pyproject.toml`, Task 1).

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from unittest.mock import MagicMock, patch

from sylvae.evidence import EvidenceRecord
from sylvae.cli import main


def make_record(status: str = "ok") -> EvidenceRecord:
    return EvidenceRecord(
        skill="summarize-diff", backend="anthropic", model="claude-sonnet-5",
        input_summary="x", output="the output", duration_ms=1,
        status=status, timestamp="2026-08-23T10:00:00+00:00",
    )


@patch("sylvae.cli.run_skill")
def test_main_prints_output_and_returns_zero_on_ok(mock_run_skill, capsys):
    mock_run_skill.return_value = make_record(status="ok")

    exit_code = main(["run", "skills/summarize-diff", "--backend", "anthropic", "--input", "hi"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "the output" in captured.out


@patch("sylvae.cli.run_skill")
def test_main_returns_one_on_non_ok_status(mock_run_skill, capsys):
    mock_run_skill.return_value = make_record(status="unavailable")

    exit_code = main(["run", "skills/summarize-diff", "--backend", "ollama", "--input", "hi"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unavailable" in captured.err


def test_main_rejects_unknown_backend_before_running():
    exit_code = main(["run", "skills/summarize-diff", "--backend", "not-real", "--input", "hi"])
    assert exit_code == 2  # argparse's own exit code for an invalid choice
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sylvae.cli'`

- [ ] **Step 3: Write minimal implementation**

`src/sylvae/cli.py`:
```python
from __future__ import annotations

import argparse
import sys

from sylvae.runner import BACKENDS, run_skill


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sylvae")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("skill_path")
    run_parser.add_argument("--backend", required=True, choices=sorted(BACKENDS))
    run_parser.add_argument("--input", required=True)

    args = parser.parse_args(argv)

    if args.command == "run":
        record = run_skill(args.skill_path, args.backend, args.input)
        print(record.output)
        if record.status != "ok":
            print(f"[{record.status}] skill run did not complete successfully", file=sys.stderr)
            return 1
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/sylvae/cli.py tests/test_cli.py
git commit -m "Add sylvae CLI"
```

---

### Task 9: Real skills

**Files:**
- Modify: `skills/summarize-diff/SKILL.md` (replace Task 2's minimal stand-in with full content)
- Create: `skills/disk-report/SKILL.md`
- Modify: `tests/test_loader.py` (add a second fixture-based test)

**Interfaces:**
- Consumes: `load_skill` from `sylvae.loader` (Task 2). No new interfaces produced — this task supplies real content the manual comparison in Task 10 runs against.

- [ ] **Step 1: Replace `skills/summarize-diff/SKILL.md` with its full content**

```markdown
---
name: summarize-diff
description: Summarize a git diff into a short, plain-language description of what changed and why it likely matters.
---

You will be given the raw output of `git diff` as task input.

Read it and produce a short summary (3-6 sentences, plain language) covering:
- which files changed and what kind of change each one is (added, removed, modified logic, renamed, config, docs)
- the likely purpose of the change, inferred from the diff itself — don't guess motivations not visible in the code
- anything that looks risky or worth a reviewer's attention (e.g. a changed function signature, a removed test, a hardcoded value)

Do not just restate the diff line by line. Do not invent context that isn't in the diff.
```

- [ ] **Step 2: Write `skills/disk-report/SKILL.md`**

```markdown
---
name: disk-report
description: Read the output of `df -h` and produce a short, actionable report flagging any filesystem at or above 85% used.
---

You will be given the raw output of `df -h` as task input.

Produce a short report (plain language, no more than 6 lines) that:
- lists any filesystem at or above 85% used, with its mount point and percentage
- says clearly if nothing is above the threshold
- does not repeat the entire table back — only the filesystems that matter

If the input doesn't look like `df -h` output, say so instead of guessing.
```

- [ ] **Step 3: Add a loader test against the new fixture**

Add to `tests/test_loader.py`:
```python
DISK_REPORT_FIXTURE = Path(__file__).parent.parent / "skills" / "disk-report"


def test_load_skill_disk_report_fixture():
    skill = load_skill(DISK_REPORT_FIXTURE)

    assert skill.slug == "disk-report"
    assert "85%" in skill.instructions
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_loader.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Commit**

```bash
git add skills/summarize-diff/SKILL.md skills/disk-report/SKILL.md tests/test_loader.py
git commit -m "Add real summarize-diff and disk-report skills"
```

---

### Task 10: Manual cross-backend comparison

This task is the actual phase-1 experiment result, not more unit-tested code. It requires a live Anthropic API key and a running local Ollama instance with a pulled model (e.g. `ollama pull qwen2.5:14b`).

**Files:**
- Create: `docs/phase1-comparison.md`

- [ ] **Step 1: Run `summarize-diff` on both live backends**

```bash
git -C /data/src/experiments/Sylvae diff HEAD~3 > /tmp/sample.diff  # or any real diff on hand
sylvae run skills/summarize-diff --backend anthropic --input /tmp/sample.diff
sylvae run skills/summarize-diff --backend ollama --input /tmp/sample.diff
```

Record each run's output, and the corresponding line from `runs/<today>.jsonl` (has `duration_ms`, `status`, `model`).

- [ ] **Step 2: Run `disk-report` on both live backends**

```bash
df -h > /tmp/disk.txt
sylvae run skills/disk-report --backend anthropic --input /tmp/disk.txt
sylvae run skills/disk-report --backend ollama --input /tmp/disk.txt
```

- [ ] **Step 3: Confirm the shellout backend fails closed as designed**

```bash
sylvae run skills/summarize-diff --backend shellout --input /tmp/sample.diff
```
Expected: exit code 1, stderr shows `[unavailable] ...`, nothing printed as if it succeeded.

- [ ] **Step 4: Write the comparison**

`docs/phase1-comparison.md` — for each of the two skills, record: output quality (does it follow the skill's own instructions, is it accurate, is it useful as-is), latency (`duration_ms` from the evidence log), and a rough cost note (Anthropic: priced per token via the API; Ollama: effectively free after the one-time local compute/model-pull cost). Close with an explicit recommendation: is phase 2 (automatic routing) worth building next, and if so, what would decide "cheap enough to route to Ollama" for a given skill.

- [ ] **Step 5: Commit**

```bash
git add docs/phase1-comparison.md
git commit -m "Record phase-1 cross-backend comparison"
```

---

## Self-Review Notes

- **Spec coverage:** loader (Task 2) → §"Skill loader"; three backends (Tasks 3-5) → §"Backend adapters"; evidence (Task 6) → §"Evidence record"; runner + CLI (Tasks 7-8) → §"Runner CLI" and §"Data flow"; error-handling status vocabulary is enforced in every backend test (Tasks 3-5) and asserted again at the CLI level (Task 8) → §"Error handling"; Task 10 is exactly the spec's §"Testing / success criteria" deliverable; Task 9's two skills satisfy "2-3 real, low-stakes skills." All three "open questions" from the spec are resolved above (Python, first skills, shellout deferral) rather than left open.
- **Placeholder scan:** no TBD/TODO. Caught and fixed one real inconsistency during review: Task 8's CLI originally referenced `record.error`, a field `EvidenceRecord` (Task 6) doesn't define — corrected to report status only, no dangling reference left.
- **Type consistency:** `BackendResult`, `Skill`, `EvidenceRecord` field names and the `BACKENDS` dict keys are used identically across Tasks 3 through 8 — checked by hand against each task's Interfaces block.
