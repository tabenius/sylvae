---
name: summarize-diff
description: Summarize a git diff into a short, plain-language description of what changed and why it likely matters.
tier: frontier
---

You will be given the raw output of `git diff` as task input.

Read it and produce a short summary (3-6 sentences, plain language) covering:
- which files changed and what kind of change each one is (added, removed, modified logic, renamed, config, docs)
- the likely purpose of the change, inferred from the diff itself — don't guess motivations not visible in the code
- anything that looks risky or worth a reviewer's attention (e.g. a changed function signature, a removed test, a hardcoded value)

Do not just restate the diff line by line. Do not invent context that isn't in the diff.
