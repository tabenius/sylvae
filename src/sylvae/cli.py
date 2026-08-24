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

    review_parser = subparsers.add_parser("review", help="Browse the evidence log in a local web page")
    review_parser.add_argument("--runs-dir", default="runs")
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

    if args.command == "review":
        serve(runs_dir=args.runs_dir, host=args.host, port=args.port)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
