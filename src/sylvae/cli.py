from __future__ import annotations

import argparse
import sys

from sylvae.review import serve
from sylvae.runner import BACKENDS, run_skill


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
    review_parser.add_argument("--host", default="127.0.0.1", help="Loopback by default — pass 0.0.0.0 to allow LAN access")
    review_parser.add_argument("--port", type=int, default=8971)

    args = parser.parse_args(argv)

    if args.command == "run":
        record = run_skill(args.skill_path, args.backend, args.input, model=args.model)
        if record.output:
            print(record.output)
        if record.status != "ok":
            detail = record.error or "skill run did not complete successfully"
            print(f"[{record.status}] {detail}", file=sys.stderr)
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
        serve(runs_dir=args.runs_dir, skills_dir=args.skills_dir, host=args.host, port=args.port)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
