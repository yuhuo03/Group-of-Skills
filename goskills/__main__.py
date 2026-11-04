import argparse
import json
from pathlib import Path
from .config import validate_config
from .io import read_json, write_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="GoSkills paper-based clean rewrite")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-native", help="Read an official GoS workspace without modifying it")
    export.add_argument("--workspace", type=Path, required=True)
    export.add_argument("--skills-root", type=Path, required=True)
    export.add_argument("--index-run-dir", type=Path)
    export.add_argument("--output", type=Path, required=True)
    build = commands.add_parser("build", help="Build reusable groups from a real directed graph export")
    build.add_argument("--graph", type=Path, required=True)
    build.add_argument("--config", type=Path)
    build.add_argument("--output", type=Path, required=True)
    query = commands.add_parser("query", help="Retrieve a bounded execution contract")
    query.add_argument("--pool", type=Path, required=True)
    content = query.add_mutually_exclusive_group(required=True)
    content.add_argument("--query")
    content.add_argument("--query-file", type=Path)
    query.add_argument("--public-context-file", type=Path, help="Explicit caller-selected public text only")
    query.add_argument("--seed-evidence", type=Path)
    query.add_argument("--source-root")
    query.add_argument("--output-json", type=Path)
    query.add_argument("--json", action="store_true")
    validate = commands.add_parser("validate-bundle")
    validate.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    if args.command == "export-native":
        from .native import export_native
        result = export_native(args.workspace, args.skills_root, args.index_run_dir)
        write_json(args.output, result)
        print(json.dumps({"output": str(args.output), "skills": len(result["skills"]), "edges": len(result["edges"])}))
    elif args.command == "build":
        from .groups import build_pool
        result = build_pool(read_json(args.graph), validate_config(read_json(args.config) if args.config else None))
        write_json(args.output, result)
        print(json.dumps({"output": str(args.output), "skills": len(result["skills"]),
                          "groups": len(result["groups"]), "group_edges": len(result["group_edges"])}))
    elif args.command == "query":
        from .retrieval import Retriever
        from .validation import validate_bundle
        text = args.query if args.query is not None else args.query_file.read_text(encoding="utf-8")
        context = args.public_context_file.read_text(encoding="utf-8") if args.public_context_file else ""
        result = Retriever(read_json(args.pool), source_root=args.source_root).query(
            text, public_context=context, seeds=read_json(args.seed_evidence) if args.seed_evidence else None)
        validate_bundle(result)
        if args.output_json:
            write_json(args.output_json, result)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else result["rendered_context"])
    else:
        from .validation import validate_bundle
        print(json.dumps(validate_bundle(read_json(args.bundle)), sort_keys=True))


if __name__ == "__main__":
    main()
