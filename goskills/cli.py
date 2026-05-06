from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .group_graph import build_group_graph
from .retrieval import retrieve


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="GoSkills build and query CLI.")
    subparsers = parser.add_subparsers(dest="command")

    build = subparsers.add_parser("build", help="Build and save a GoSkills bundle.")
    build.add_argument("--bundle", type=Path, required=True, help="Input flat skill bundle JSON.")
    build.add_argument("--output", type=Path, required=True, help="Output bundle with GoSkills group_graph metadata.")
    build.add_argument("--max-group-size", type=int, default=3, help="Maximum atomic skills per anchor group.")

    query = subparsers.add_parser("query", help="Query a GoSkills bundle.")
    query.add_argument("query", nargs="?", default="", help="Task or subproblem description.")
    query.add_argument("--bundle", type=Path, required=True, help="Bundle JSON path.")
    query.add_argument("--top-n", type=int, default=4, help="Maximum atomic skills in the returned coalition.")
    query.add_argument("--seed-top-k", type=int, default=4, help="Seed skills used for group activation.")
    query.add_argument("--seed-mode", choices=("lexical",), default="lexical")
    query.add_argument("--propagation-mode", choices=("ppr", "none"), default="ppr")
    query.add_argument("--max-skill-chars", type=int, default=1800)
    query.add_argument("--max-context-chars", type=int, default=9000)
    query.add_argument("--json", action="store_true", help="Print full JSON result.")
    query.add_argument("--raw", action="store_true", help="Print rendered context instead of summary.")

    return parser


def run_build(args: argparse.Namespace) -> None:
    bundle = load_json(args.bundle)
    updated = build_group_graph(bundle, max_group_size=args.max_group_size)
    write_json(args.output, updated)
    graph = updated.get("group_graph", {})
    print(f"GoSkills bundle: {args.output}")
    print(f"Groups: {len(graph.get('groups', []))}")
    print(f"Group edges: {len(graph.get('edges', []))}")


def run_query(args: argparse.Namespace) -> None:
    bundle = load_json(args.bundle)
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
        return
    if args.raw:
        print(result["rendered_context"])
        return
    print(result["summary"])


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "build":
        run_build(args)
        return
    if args.command == "query":
        run_query(args)
        return
    parser.print_help()


if __name__ == "__main__":
    main()
