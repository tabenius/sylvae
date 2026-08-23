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
        if record.output:
            print(record.output)
        if record.status != "ok":
            print(f"[{record.status}] skill run did not complete successfully", file=sys.stderr)
            return 1
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
