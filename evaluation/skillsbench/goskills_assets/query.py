#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT_CANDIDATES = [
    Path(__file__).resolve().parent,
    Path(__file__).resolve().parents[3],
]
for root in ROOT_CANDIDATES:
    if (root / "goskills").exists() and str(root) not in sys.path:
        sys.path.insert(0, str(root))
        break

from goskills.retrieval import retrieve  # noqa: E402


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="Query the local GoSkills benchmark bundle.")
    parser.add_argument("query", nargs="?", default="", help="Task or subproblem description.")
    parser.add_argument("--bundle", type=Path, default=script_dir / "bundle.json")
    parser.add_argument("--top-n", type=int, default=4)
    parser.add_argument("--seed-top-k", type=int, default=4)
    parser.add_argument(
        "--seed-mode",
        choices=("lexical",),
        default=os.getenv("GOSKILLS_SEED_MODE", "lexical"),
    )
    parser.add_argument(
        "--propagation-mode",
        choices=("ppr", "none"),
        default=os.getenv("GOSKILLS_PROPAGATION_MODE", "ppr"),
    )
    parser.add_argument("--max-skill-chars", type=int, default=1800)
    parser.add_argument("--max-context-chars", type=int, default=9000)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--raw", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
    result = retrieve(
        bundle,
        args.query,
        top_n=args.top_n,
        seed_top_k=args.seed_top_k,
        max_skill_chars=args.max_skill_chars,
        max_context_chars=args.max_context_chars,
        seed_mode=args.seed_mode,
        propagation_mode=args.propagation_mode,
        vector_store_path=None,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.raw:
        print(result["rendered_context"])
    else:
        print(result["summary"])


if __name__ == "__main__":
    main()
