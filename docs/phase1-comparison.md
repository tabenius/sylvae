# Phase 1: cross-backend comparison

Manual, exploratory comparison of Sylvae's backends against the two real skills
(`skills/summarize-diff`, `skills/disk-report`). This is the actual phase-1
experiment result the pipeline (Tasks 1-9, 21 passing tests) was built to
produce evidence for.

## Scope adjustment from the original task brief

The brief assumed two live backends (Anthropic + Ollama) both reachable with a
pulled model. The actual environment only supports one of those cleanly:

- **Ollama** is running at `http://localhost:11434` with `mistral:latest` and
  `mistral:7b-instruct-q4_0` pulled — but not `qwen2.5:14b`,
  `OllamaBackend`'s hardcoded default. Pulling a 14B model just for this
  comparison wasn't worth the download, so the two real-content runs below use
  `mistral:latest` via a short script instead of the CLI (see [Gap: no
  `--model` CLI flag](#gap-no---model-cli-flag)).
- **Anthropic** has no `ANTHROPIC_API_KEY` set anywhere in this environment
  (checked `env`, checked the repo's secrets-exposure conventions — nothing
  usable there either). A live `--backend anthropic` call would only crash on
  missing credentials, which teaches nothing. This is documented as an
  explicit gap below rather than worked around.
- **shellout** needs no external service and was run as originally specified.

Test inputs: a real diff from this repo's own history
(`git diff a126ccb 6c71dde`, the "Add real summarize-diff and disk-report
skills" commit) and real `df -h` output from this machine (root filesystem at
92% used — a genuine above-threshold case, which turned out to be a useful
test of the skill's threshold logic).

## Run 1: `summarize-diff` on Ollama (`mistral:latest`)

Run via a throwaway script calling the loader/runner/backend API directly
(`load_skill` → `resolve_input` → `build_prompt` → `OllamaBackend(model="ollama/mistral:latest").run(...)`),
because the CLI has no way to select a non-default Ollama model. The script
still writes through the real `append_evidence` path, so the run is in
`runs/2026-08-23.jsonl` like any other.

**Evidence record:**
```json
{
  "skill": "summarize-diff",
  "backend": "ollama",
  "model": "ollama/mistral:latest",
  "status": "ok",
  "duration_ms": 194741
}
```

**Output:**
```
Summary:

1. A new file named `disk-report.md` has been added under the `skills/disk-report/` directory. This file describes a new skill that reads the output of `df -h` and produces a report highlighting any filesystems at or above 85% used. The purpose of this change is to create a new skill that automates the process of monitoring and reporting on disk usage.

2. In the `skills/summarize-diff/SKILL.md` file, the description of the existing skill 'summarize-diff' has been updated to reflect a more detailed summary of the git diff, including the likely purpose of the change.

3. In the `tests/test_loader.py` file, a new function named `test_load_skill_disk_report_fixture()` has been added. This function loads the new 'disk-report' skill from its fixture and checks its properties. This change suggests that the testing framework for skills has been expanded to include the new 'disk-report' skill.

The following changes do not appear to be risky, but they might be worth a reviewer's attention:

- The changed function signature in `tests/test_loader.py`: The new function `test_load_skill_disk_report_fixture()` adds a new test for the 'disk-report' skill. It might be worth verifying that this test correctly covers all edge cases and error scenarios.

- The addition of the `DISK_REPORT_FIXTURE` in `tests/test_loader.py`: This constant specifies the path to the fixture for the 'disk-report' skill. It might be worth verifying that this path is correct and that the fixture contains the expected 'disk-report.md' file.
```

**Assessment:** Mostly follows the skill's instructions — it correctly
identifies the three changed files and their kind of change, and does not
just restate the diff line by line. Two real weaknesses:
- It calls out `test_loader.py` as containing "a changed function signature,"
  which is inaccurate — the diff *adds* a new test function, it doesn't
  change an existing signature. The skill explicitly warns against inventing
  context not in the diff, and this is a small factual slip in that
  direction.
- The "risky" section is padding — a new test and a new fixture constant
  aren't actually risky, and the skill asks for things "worth a reviewer's
  attention," which this technically satisfies but weakly. A stronger answer
  would have said "nothing here looks risky" and stopped.

Usable as a first draft a human would still skim and lightly edit, not as a
final answer to trust unread.

**Latency:** 194,741 ms (~3 minutes 15 seconds) for a 62-line diff. Slow
enough to be a real UX cost in an interactive workflow.

## Run 2: `disk-report` on Ollama (`mistral:latest`)

**Evidence record:**
```json
{
  "skill": "disk-report",
  "backend": "ollama",
  "model": "ollama/mistral:latest",
  "status": "ok",
  "duration_ms": 29475
}
```

**Output:**
```
Only the root filesystem at /dev/vda1 is above 85% usage, with 92% usage. The others are below the threshold.
```

**Assessment:** Excellent. One line, correctly identifies the single
filesystem above the 85% threshold (`/dev/vda1` at 92%), correctly states
that nothing else qualifies, doesn't repeat the whole table. This is exactly
what the skill asks for and is usable as-is with zero editing.

**Latency:** 29,475 ms (~30 seconds). Much faster than `summarize-diff` —
consistent with a much smaller output (one sentence vs. a multi-paragraph
summary) and a smaller effective context (13 lines of `df -h` output vs. a
62-line diff).

## Finding: requesting an unpulled model surfaces as `unavailable`, not `failed`

Ran the real CLI end-to-end to see what happens when the requested model
isn't pulled:

```
$ sylvae run skills/summarize-diff --backend ollama --input /tmp/sample.diff
[unavailable] skill run did not complete successfully
exit code: 1
```

Evidence record:
```json
{
  "skill": "summarize-diff",
  "backend": "ollama",
  "model": "ollama/qwen2.5:14b",
  "status": "unavailable",
  "duration_ms": 37
}
```

Traced this to litellm's exception hierarchy: Ollama's server-side response
to a missing model (`{"error":"model 'qwen2.5:14b' not found"}`, a normal
HTTP 404 from a live, reachable server) gets wrapped by litellm as
`litellm.exceptions.APIConnectionError` — the *same* exception class
`OllamaBackend` catches for "the server isn't reachable at all." Verified
directly:

```python
>>> litellm.completion(model='ollama/qwen2.5:14b', api_base='http://localhost:11434', ...)
litellm.APIConnectionError: OllamaException - {"error":"model 'qwen2.5:14b' not found"}
```

**Is `unavailable` the right classification here?** Debatable, and worth
flagging rather than silently accepting. `OllamaBackend`'s except-clause
ordering (`APIConnectionError` → `unavailable`, anything else → `failed`)
was clearly written with "service down" in mind, and a missing-model 404
happens to land in the same bucket only because litellm's exception taxonomy
conflates "can't reach the host" with "reached the host, it said no." For a
router (phase 2) trying to decide "retry a different backend" vs. "retry the
same backend with a different model" vs. "give up," these are meaningfully
different failure modes that the current status vocabulary (`ok` / `failed`
/ `unavailable`) can't tell apart. Not a bug in the strict sense — the
run does fail closed, correctly, with a clear message — but it's a
resolution gap worth fixing before phase 2 tries to make automatic decisions
based on this field.

## Finding: shellout backend fails closed as designed

```
$ sylvae run skills/summarize-diff --backend shellout --input /tmp/sample.diff
[unavailable] skill run did not complete successfully
exit code: 1
```

stdout is empty (nothing printed as if the run succeeded); stderr carries the
`[unavailable] ...` message; exit code is 1. Confirmed twice, with stdout and
stderr captured separately to be sure nothing leaked onto stdout. Evidence
record: `status: "unavailable"`, `duration_ms: 0`, `model: "codex"`. Exactly
as designed — `ShelloutBackend` is an intentional not-implemented stub for
phase 1, and it fails the same way a real "can't run this" case should.

## Gap: no `ANTHROPIC_API_KEY` in this environment

No Anthropic-backed run was attempted. `ANTHROPIC_API_KEY` is unset (checked
`env`, checked the repo's secrets conventions doc — nothing usable there
either), and `AnthropicBackend` would only raise on client construction or on
the first API call. Forcing that call would just prove "no key set fails,"
which isn't a finding worth spending an API-crash on. This is a real,
acknowledged gap in this comparison, not a finding: **the Anthropic side of
phase 1's "two live backends" comparison could not be run in this
environment.** Anyone repeating this experiment with a key available should
fill in this half — output quality and latency numbers for
`claude-sonnet-5` against the same two skills and the same two inputs would
slot directly into the sections above.

## Gap: no `--model` flag on the CLI

`sylvae run` (`src/sylvae/cli.py`) only accepts `skill_path`, `--backend`,
and `--input`. There is no way to choose which model a backend uses from the
command line — `OllamaBackend`'s `model="ollama/qwen2.5:14b"` and
`AnthropicBackend`'s `model="claude-sonnet-5"` are both hardcoded
constructor defaults, and `BACKENDS[backend_name]()` in `runner.py`
instantiates with no arguments. This is why the two real-content runs above
were done through a script calling the public API directly instead of
through `sylvae run` — there was no CLI-only way to point `OllamaBackend` at
the one model that's actually pulled in this environment. Worth fixing
regardless of whether phase 2 happens: even a single-backend, single-model
phase 1 user will eventually want to try a different local model without
editing source.

## Cost note

- **Anthropic:** priced per input/output token via the API. Not measured
  here (no key), but non-zero and scales with usage — the cost that matters
  is marginal cost per call.
- **Ollama:** effectively free per call once the model is pulled and the
  host has the RAM/CPU to run it — the real cost is the one-time
  model-pull/disk cost plus the wall-clock latency tax observed above (30s
  to 3m15s per call on this host's hardware, for a small 7B model — a 14B
  model would be slower still).

## Recommendation

**Phase 2 (automatic routing) is worth building, but only after two gaps
above are closed, not before:**

1. **Fix the status vocabulary before automating decisions on it.** A router
   that sees `unavailable` today can't tell "Ollama is down, try Anthropic"
   from "Ollama is up but this specific model isn't pulled, try a different
   model on Ollama" — and those call for different automatic responses. This
   is a small, contained fix (distinguish connection failure from a 4xx
   model-not-found response) and it's a prerequisite for any routing logic
   that reads `BackendResult.status`.
2. **Add the `--model` flag** so routing can actually choose between models,
   not just backends — "cheap enough to route to Ollama" is a
   skill-and-model question, not just a skill-and-backend question, and the
   CLI currently can't express the model half of that decision even
   manually.

Given those, what should decide "cheap enough to route to Ollama" for a
given skill, based on what this comparison actually showed:

- **Output length/complexity vs. skill tolerance for imprecision.**
  `disk-report` was a clean win for Ollama: short, mechanical,
  pattern-matching task (find the rows above a threshold), and a small local
  model nailed it in 30 seconds with zero editing needed.
  `summarize-diff` is a worse fit as tested: it requires synthesis and
  restraint (don't invent, don't over-flag), and mistral both slipped on
  one factual detail and padded a section that should have said "nothing
  risky here." A phase-2 router should treat "short, mechanical,
  low-ambiguity output" as the green flag for Ollama, and "requires judgment
  calls the skill explicitly warns against getting wrong" as the flag to
  keep on Anthropic — at least until a stronger local model is benchmarked.
- **Latency budget of the caller.** 30 seconds is fine for `disk-report` run
  ad hoc or on a schedule; 3+ minutes for `summarize-diff` is a real tax in
  an interactive review flow. If phase 2 routing exists, it should be able
  to weigh "is this call blocking a human right now" as well as "is this
  skill's output tolerant of a smaller model," since the two skills tested
  here split differently on quality and on latency.
- **A larger local model is worth benchmarking before concluding Ollama
  can't handle `summarize-diff`-shaped tasks.** `qwen2.5:14b` (the
  backend's own hardcoded default) wasn't available to test here, and a
  bigger model might close the gap seen in Run 1. That's a natural first
  phase-2 experiment: pull `qwen2.5:14b`, rerun `summarize-diff` through it,
  and see whether the factual-accuracy and restraint issues persist.
