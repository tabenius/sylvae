from __future__ import annotations

import argparse
import json
import sys

from sylvae.color import color_enabled, paint, status_styles
from sylvae.evidence import runtime_ref_for
from sylvae.loader import SkillLoadError
from sylvae.review import ReviewConfigError, load_all_runs, serve
from sylvae.runner import BACKENDS, run_skill


def _completion_script(shell: str, commands: list[str]) -> str:
    """A dependency-free completion script for ``sylvae`` that completes the
    top-level subcommands. Derived from the live command list so it stays in
    sync with the parser."""
    cmds = " ".join(commands)
    if shell == "bash":
        return (
            "# sylvae bash completion.\n"
            '# Setup: eval "$(sylvae completion bash)"  (add to ~/.bashrc), or\n'
            "#   sylvae completion bash | sudo tee /etc/bash_completion.d/sylvae\n"
            "_sylvae_complete() {\n"
            '    local cur="${COMP_WORDS[COMP_CWORD]}"\n'
            '    if [ "$COMP_CWORD" -eq 1 ]; then\n'
            f'        COMPREPLY=( $(compgen -W "{cmds}" -- "$cur") )\n'
            "    fi\n"
            "}\n"
            "complete -F _sylvae_complete sylvae\n"
        )
    if shell == "fish":
        lines = [
            "# sylvae fish completion.",
            "# Setup: sylvae completion fish > ~/.config/fish/completions/sylvae.fish",
            "complete -c sylvae -f",
        ]
        lines += [
            f"complete -c sylvae -n __fish_use_subcommand -a {cmd}" for cmd in commands
        ]
        return "\n".join(lines) + "\n"
    raise ValueError(f"unsupported shell: {shell}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sylvae")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("skill_path")
    run_parser.add_argument("--backend", required=True, choices=sorted(BACKENDS) + ["auto"])
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument(
        "--model",
        default=None,
        help="Override the backend's default model (e.g. 'ollama/mistral:latest'). Omit to use the backend's default.",
    )
    run_parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Use a preallocated 32-character UUID hex run id. This lets a "
            "coordinator attribute external evidence to sylvae:run/<id>."
        ),
    )

    mcp_parser = subparsers.add_parser(
        "mcp", help="Run an MCP server exposing skills to agents (needs the 'mcp' extra)"
    )
    mcp_parser.add_argument("--runs-dir", default="runs")
    mcp_parser.add_argument("--skills-dir", default="skills")
    mcp_parser.add_argument(
        "--allow-recursive-backends",
        action="store_true",
        help=(
            "Permit backends that spawn an agent harness (e.g. claudecode). Off by "
            "default: such a backend can call Sylvae again and spends your own "
            "interactive quota. This is your decision, not the calling model's."
        ),
    )
    mcp_parser.add_argument(
        "--dependency-log-level",
        default="warning",
        choices=["critical", "error", "warning", "info", "debug"],
        help=(
            "Level for noisy dependency loggers (litellm, httpx, ...). Default "
            "'warning'. CAUTION: while serving over stdio the MCP SDK points fd 1 at "
            "stderr, and clients commonly capture stderr to a log file. At 'info' or "
            "'debug' these libraries log full request/response bodies — which for "
            "Sylvae is the skill's input and output — so raising this writes "
            "caller-supplied content to disk. Use for debugging, not routinely."
        ),
    )

    review_parser = subparsers.add_parser("review", help="Browse the evidence log in a local web page")
    review_parser.add_argument("--runs-dir", default="runs")
    review_parser.add_argument("--skills-dir", default="skills")
    review_parser.add_argument("--host", default="127.0.0.1", help="Loopback by default. Binding beyond loopback (e.g. 0.0.0.0 for LAN access) requires SYLVAE_REVIEW_TOKEN; every request must then send it as a Bearer token.")
    review_parser.add_argument("--port", type=int, default=8971)

    runs_parser = subparsers.add_parser(
        "runs", help="List recorded runs from the evidence log (most recent first)"
    )
    runs_parser.add_argument("--runs-dir", default="runs")
    runs_parser.add_argument("--skill", default=None, help="Only runs of this skill")
    runs_parser.add_argument("--backend", default=None, help="Only runs on this backend")
    runs_parser.add_argument(
        "--status", default=None, help="Only runs with this status (ok | failed | unavailable)"
    )
    runs_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Show at most this many (most recent first); 0 for all. Default 20.",
    )
    runs_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON array (includes each run's runtime_ref) instead of a table.",
    )

    show_parser = subparsers.add_parser(
        "show", help="Show one recorded run's full detail (input, output, error) by run id"
    )
    show_parser.add_argument(
        "run_id",
        help="The run's id, or an unambiguous prefix of it.",
    )
    show_parser.add_argument("--runs-dir", default="runs")
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the raw record (plus its runtime_ref) as JSON.",
    )

    completion_parser = subparsers.add_parser(
        "completion", help="Print a shell completion script (bash or fish)"
    )
    completion_parser.add_argument("shell", choices=("bash", "fish"))

    args = parser.parse_args(argv)

    if args.command == "completion":
        print(_completion_script(args.shell, sorted(subparsers.choices)), end="")
        return 0

    if args.command == "run":
        # A malformed SKILL.md is an ordinary authoring mistake -- a tier
        # typo, a missing key -- not an internal fault. Since tier values are
        # now validated strictly, this is a path users will hit routinely,
        # and a traceback is the wrong way to tell someone they wrote
        # `tier: cheep`.
        try:
            record = run_skill(
                args.skill_path,
                args.backend,
                args.input,
                model=args.model,
                run_id=args.run_id,
            )
        except (SkillLoadError, ValueError) as exc:
            print(f"[error] {exc}", file=sys.stderr)
            return 1
        if record.output:
            print(record.output)
        if record.status != "ok":
            detail = record.error or "skill run did not complete successfully"
            tag = paint(
                f"[{record.status}]", *status_styles(record.status), stream=sys.stderr
            )
            print(f"{tag} {detail}", file=sys.stderr)
            return 1
        return 0

    if args.command == "mcp":
        import logging

        from sylvae.mcp.server import McpDependencyError, serve as serve_mcp

        try:
            serve_mcp(
                skills_dir=args.skills_dir,
                runs_dir=args.runs_dir,
                allow_recursive_backends=args.allow_recursive_backends,
                dependency_log_level=getattr(logging, args.dependency_log_level.upper()),
            )
        except McpDependencyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if args.command == "review":
        try:
            serve(runs_dir=args.runs_dir, skills_dir=args.skills_dir, host=args.host, port=args.port)
        except ReviewConfigError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    if args.command == "runs":
        records = load_all_runs(args.runs_dir)  # most recent first
        if args.skill is not None:
            records = [r for r in records if r.get("skill") == args.skill]
        if args.backend is not None:
            records = [r for r in records if r.get("backend") == args.backend]
        if args.status is not None:
            records = [r for r in records if r.get("status") == args.status]
        if args.limit and args.limit > 0:
            records = records[: args.limit]

        def _ref(record: dict) -> str:
            run_id = record.get("run_id") or ""
            return runtime_ref_for(run_id) if run_id else ""

        if args.json:
            # A stable projection: the fields a coordinator/operator correlates
            # on, plus the derived runtime_ref that never lands in the log.
            projection = [
                {
                    "run_id": r.get("run_id", ""),
                    "runtime_ref": _ref(r),
                    "skill": r.get("skill", ""),
                    "backend": r.get("backend", ""),
                    "model": r.get("model", ""),
                    "status": r.get("status", ""),
                    "duration_ms": r.get("duration_ms"),
                    "timestamp": r.get("timestamp", ""),
                }
                for r in records
            ]
            print(json.dumps(projection, indent=2))
            return 0

        if not records:
            print("No runs recorded.", file=sys.stderr)
            return 0

        headers = ("TIMESTAMP", "STATUS", "SKILL", "BACKEND", "RUNTIME_REF")
        rows = [
            (
                r.get("timestamp", ""),
                r.get("status", ""),
                r.get("skill", ""),
                r.get("backend", ""),
                _ref(r),
            )
            for r in records
        ]
        widths = [
            max(len(headers[i]), *(len(row[i]) for row in rows))
            for i in range(len(headers))
        ]
        use_color = color_enabled()

        def _render(cols: tuple[str, ...], *, is_header: bool) -> str:
            out = []
            for i in range(len(headers)):
                # Pad on the plain text, then color -- ANSI codes are
                # zero-width, so columns stay aligned.
                cell = cols[i].ljust(widths[i])
                if is_header:
                    cell = paint(cell, "bold", enabled=use_color)
                elif i == 1:  # STATUS
                    cell = paint(cell, *status_styles(cols[i]), enabled=use_color)
                out.append(cell)
            return "  ".join(out)

        print(_render(headers, is_header=True))
        for row in rows:
            print(_render(row, is_header=False))
        return 0

    if args.command == "show":
        records = load_all_runs(args.runs_dir)
        want = args.run_id
        exact = [r for r in records if r.get("run_id") == want]
        # Fall back to an unambiguous prefix so a short id works (run ids are
        # 32 hex chars); an ambiguous prefix is refused rather than guessed.
        matches = exact or [
            r for r in records if str(r.get("run_id", "")).startswith(want)
        ]
        if not matches:
            print(f"No run found for '{want}'.", file=sys.stderr)
            return 1
        if len(matches) > 1 and not exact:
            ids = ", ".join(sorted(str(r.get("run_id", "")) for r in matches)[:5])
            print(
                f"'{want}' is ambiguous ({len(matches)} runs match): {ids}...",
                file=sys.stderr,
            )
            return 1
        record = matches[0]
        run_id = str(record.get("run_id", ""))

        if args.json:
            # The stored record verbatim, plus the derived runtime_ref that never
            # lands in the log.
            print(json.dumps({**record, "runtime_ref": runtime_ref_for(run_id)}, indent=2))
            return 0

        fields = (
            ("run_id", run_id),
            ("runtime_ref", runtime_ref_for(run_id)),
            ("skill", record.get("skill", "")),
            ("backend", record.get("backend", "")),
            ("model", record.get("model", "")),
            ("status", record.get("status", "")),
            ("duration_ms", record.get("duration_ms", "")),
            ("timestamp", record.get("timestamp", "")),
        )
        label_width = max(len(name) for name, _ in fields)
        use_color = color_enabled()
        for name, value in fields:
            shown = value
            if name == "status":
                shown = paint(str(value), *status_styles(str(value)), enabled=use_color)
            print(f"{name.ljust(label_width)}  {shown}")
        if record.get("input_summary"):
            print("\n" + paint("--- input ---", "bold", enabled=use_color))
            print(record["input_summary"])
        if record.get("output"):
            print("\n" + paint("--- output ---", "bold", enabled=use_color))
            print(record["output"])
        if record.get("error"):
            print("\n" + paint("--- error ---", "bold", "red", enabled=use_color))
            print(record["error"])
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
