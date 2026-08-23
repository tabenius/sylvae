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
