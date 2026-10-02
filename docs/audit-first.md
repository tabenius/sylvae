# Audit-first run records

Sylvae records `skill.run.requested` in a `nostoi-v1` chain before invoking a
backend. The request identifies the run, skill, backend and model, and stores
the full resolved input with its digest. The input is limited to 100,000
characters, matching the MCP ceiling; CLI and review-server calls use the same
limit. Treat the chain as sensitive data and restrict access to the runs
directory. Configure `SYLVAE_NOSTOI_LEDGER` to choose a separate chain path or
`SYLVAE_NOSTOI_PYTHON` to locate the reference writer outside the workspace.

On return or provider failure, Sylvae appends a compact outcome linked to the
intent digest. It does not copy provider output into the chain; the existing
dated evidence JSONL remains the detailed result store. A request with no
outcome means the provider may have started and needs reconciliation.

The process admits at most 60 runs per rolling minute. The first rejected
burst in a UTC minute writes one compact chain entry; later rejects in that
minute do not add records. MCP also retains its 90-second timeout, 100,000
character input ceiling, and recursion guard. If exposed beyond local stdio,
apply authentication, request limits and rate controls at the network edge;
the in-process budget is not a distributed limiter.
