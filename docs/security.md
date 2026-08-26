# Security notes

What Sylvae defends against, what it deliberately doesn't, and why. Every
item under "Fixed" was demonstrated against this codebase, not imagined.

## Threat model in one line

Sylvae takes caller-supplied text and asks a model to act on it, then
records the result. Two of its surfaces are reachable by something other
than a person sitting at a terminal: the review web UI (a browser) and the
MCP server (**another model**). The MCP surface is the sharper one — text
Sylvae is asked to process could contain instructions aimed at the caller,
so parameters arriving there are untrusted in a way CLI arguments are not.

## Fixed

### Path traversal via skill name — MCP service and review UI

A `skill` value of `../../../../../tmp/evil-skill` loaded and ran a
`SKILL.md` planted outside the configured skills directory. Confirmed
exploitable before the fix.

This was the **same defect twice**. It was found and fixed in the review UI
first (commit `1004f02`, from an automated security review), then
reintroduced in the MCP service, which was written later and did not carry
the lesson across. That is why the fix now lives in `loader.py` — at the
point every caller passes through — rather than being repeated per surface:

- `validate_skill_slug()` — an anchored pattern; a slug is one plain
  directory name, no separators, no parent references, no leading dot.
- `resolve_skill_dir()` — resolves, then asserts containment. This is a
  *second, independent* check, not belt-and-braces decoration: it catches
  what a pattern structurally cannot, namely a symlink inside `skills/`
  pointing out of it, whose name is a perfectly ordinary word.

The review UI's allowlist (only slugs `list_skills()` discovered) was sound
against `../` but not against that symlink case, since such a directory is
genuinely discovered. It now also goes through `resolve_skill_dir()`.

### Argument injection via model identifier — all three CLI backends

`model="--dangerously-bypass-approvals-and-sandbox"` placed that token into
the argv handed to `codex`. It is a real codex flag that disables its
sandbox.

Whether a downstream parser reads a dash-prefixed token as the preceding
flag's *value* or as a flag *in its own right* is version-dependent
behaviour of somebody else's argument parser. That is not something to
depend on for a security property, so `validate_model_name()` in
`backends/base.py` refuses it before any process is spawned.

Shell metacharacters are refused for a different reason. They are **not**
exploitable today — every backend builds argv as a list and none ever goes
through a shell. But a model id containing them is malformed under any
reading, and refusing them now means a future backend that does build a
command string cannot quietly reintroduce the question.

### Unbounded calls and request bodies

Three availability gaps, found by inspection rather than by anything
breaking:

**Two backends had no timeout at all on the model call.** Only Ollama's 3s
availability probe was bounded; `litellm.completion()` and
`client.messages.create()` were not. A hung or slow server hung Sylvae
itself — the CLI, a review-server thread, or the MCP server. All five
backends now take a `timeout` and enforce it on the call.

**The MCP timeout was dead config.** `McpToolService` stored it, the
docstring advertised it as stricter than the CLI's 180s, and it was never
passed to anything — `run_skill()` did not even accept one. MCP calls
actually ran to the backend default. Config that *looks* enforced is worse
than none, because it is believed. `run_skill()` now takes a timeout and
forwards it to backend construction; tested end to end.

**The review server read `Content-Length` bytes with no cap and no
validation.** Garbage raised `ValueError` into a traceback; a large value
was a memory-exhaustion lever for anyone who could reach the port. Now
capped at `MAX_REQUEST_BYTES` (1 MB) and validated, rejecting on the
*declared* size before any body is read. Verified live: garbage → 400,
a header claiming 900 MB → 413 with nothing read, 2 MB body → 413,
ordinary requests unaffected.

MCP input is separately capped at `MAX_INPUT_CHARS` (100k). An unbounded
prompt is unbounded cost, and that surface is driven by a model passing
text that may itself have come from somewhere untrusted.

## Tested and NOT vulnerable

Recorded so nobody spends time "fixing" it: **YAML alias-expansion bombs
against `SKILL.md`**. A billion-laughs payload was constructed and run
through `yaml.safe_load()` — 352 source bytes, nine levels of aliasing.
It completed in under 0.1s at 11 MB RSS, because PyYAML shares alias
references rather than deep-copying them. There is no blowup to defend
against here.

## Accepted, with reasons

### Subprocess environment inheritance

The Codex, OpenCode and Claude Code backends inherit the full parent
environment, so any secret in `os.environ` is visible to them.

Accepted: these are the operator's own already-authenticated CLIs, and they
*need* their credentials from the environment to work at all. A curated
allowlist would have to enumerate every variable each tool needs, across
versions — likely to break the tools while providing little, since a
compromised local CLI has the operator's home directory anyway.

Worth revisiting if a backend is ever added that shells out to something
less trusted.

### Prompt injection into the delegated model

Skill input becomes part of a prompt. Injected instructions there can
change what the downstream model *says*.

Accepted, and bounded by design: a Sylvae run is a single text-in/text-out
call. Backends get no tools, no file access, no network beyond the model
call itself. The blast radius is a wrong answer in the output field, which
is why output is treated as data to be read — never executed, never fed to
a shell.

The MCP guards matter here: `claudecode` is refused over MCP precisely
because it is the one backend that spawns an agent *with* tools.

### Caller content written to disk

Two paths put skill input and output on disk: the evidence log, and
dependency logs on stderr when `--dependency-log-level` is raised.

`runs/` is gitignored. `docs/phase1-runs.jsonl` **is committed** — reviewed,
and it contains only disk-usage output and diffs of this repo's own skill
files. The practice to keep: that file is a curated phase-1 artifact, not a
place to refresh from a live log without reading what is in it first.

The dependency-log risk is documented on the flag itself, which states that
raising it writes caller-supplied content to disk.

### The review UI has no authentication

Bound to loopback by default, with an Origin check on state-changing POSTs.
`--host 0.0.0.0` removes the network boundary and there is no auth behind
it — anyone who can reach the port can spend money.

Accepted for a local dev tool; the flag's help says loopback is the default
on purpose. Anything beyond loopback needs a real auth story first.

## Testing

`tests/test_security.py` holds regression tests for both fixed defects,
including the symlink-escape case and the specific hostile flag values.
`tests/test_mcp_transport_integrity.py` separately proves the MCP wire
survives a tool doing `print()`, `sys.stdout.write()` and raw
`os.write(1, ...)`.
