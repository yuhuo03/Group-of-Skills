#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


GOSKILLS_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = Path(os.environ.get("GOS_WORKSPACE_ROOT", GOSKILLS_ROOT.parent)).resolve()
DEFAULT_GRAPH_OF_SKILLS_ROOT = Path(
    os.environ.get("GRAPH_OF_SKILLS_ROOT", str(WORKSPACE_ROOT / "graph-of-skills"))
).resolve()
SKILLSBENCH_ROOT = Path(__file__).resolve().parent
ASSETS_DIR = SKILLSBENCH_ROOT / "goskills_assets"
TEMPLATE_DIR = SKILLSBENCH_ROOT / "_goskills_template"
BOOTSTRAP_SKILL_DIR = GOSKILLS_ROOT / "skills" / "goskills-retriever"
QUERY_TEMPLATE = ASSETS_DIR / "query.py"
GOSKILLS_PACKAGE_DIR = GOSKILLS_ROOT / "goskills"
DEFAULT_OUTPUT_ROOT = SKILLSBENCH_ROOT / "generated"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def load_baseline_module(graph_of_skills_root: Path) -> ModuleType:
    module_path = graph_of_skills_root / "evaluation" / "skillsbench" / "graphskills_benchmark.py"
    if not module_path.exists():
        raise FileNotFoundError(f"Missing baseline generator: {module_path}")
    return load_module("gos_graphskills_benchmark_for_goskills", module_path)


def load_goskills_module() -> ModuleType:
    if str(GOSKILLS_ROOT) not in sys.path:
        sys.path.insert(0, str(GOSKILLS_ROOT))
    import goskills.group_graph as goskills_builder

    return goskills_builder


def hardlink_or_copy_file(source: Path, destination: Path, baseline: ModuleType) -> None:
    baseline.hardlink_or_copy_file(source, destination)


def render_compose_template(
    template_path: Path,
    *,
    destination_env_dir: Path,
    skills_root: Path,
    baseline: ModuleType,
) -> str:
    return baseline.render_compose_template(
        template_path,
        destination_env_dir=destination_env_dir,
        skills_root=skills_root,
        gos_workspace=None,
    )


def build_docker_block() -> str:
    instruction_block = [
        "COPY CLAUDE.md /root/CLAUDE.md",
        "COPY AGENTS.md /root/AGENTS.md",
        "COPY GEMINI.md /root/GEMINI.md",
        'RUN for d in /app /app/workspace /app/video /root /workspace /repo; do '
        'if [ -d "$d" ]; then '
        'cp /root/CLAUDE.md "$d/CLAUDE.md" 2>/dev/null || true; '
        'cp /root/AGENTS.md "$d/AGENTS.md" 2>/dev/null || true; '
        'cp /root/GEMINI.md "$d/GEMINI.md" 2>/dev/null || true; '
        'fi; '
        'done',
    ]
    lines = [
        "# BEGIN GOSKILLS BENCHMARK",
        "RUN if command -v python3 >/dev/null 2>&1; then :; "
        "elif command -v apt-get >/dev/null 2>&1; then "
        "apt-get update && apt-get install -y --no-install-recommends --allow-unauthenticated python3 && rm -rf /var/lib/apt/lists/*; "
        'else echo "python3 is required for goskills-query" >&2; exit 1; fi',
        "COPY goskills /opt/goskills",
        "RUN chmod +x /opt/goskills/query.py && ln -sf /opt/goskills/query.py /usr/local/bin/goskills-query",
        "ENV GOSKILLS_ROOT=/opt/goskills",
        *instruction_block,
        "# END GOSKILLS BENCHMARK",
    ]
    return "\n".join(lines)


def patch_dockerfile(dockerfile_path: Path, baseline: ModuleType) -> None:
    original = dockerfile_path.read_text(encoding="utf-8")
    patterns = [
        ("# BEGIN GRAPH SKILLS BENCHMARK", "# END GRAPH SKILLS BENCHMARK"),
        ("# BEGIN GOSKILLS BENCHMARK", "# END GOSKILLS BENCHMARK"),
    ]
    updated = original
    for begin, end in patterns:
        updated = re.sub(
            rf"{re.escape(begin)}.*?{re.escape(end)}\n?",
            "",
            updated,
            flags=re.DOTALL,
        )
    updated = re.sub(r"(?m)^\s*COPY\s+skills(?:[^\n]*)\n?", "", updated)
    updated = updated.rstrip()
    updated = f"{updated}\n\n{build_docker_block()}\n"
    updated = baseline.patch_dockerfile_text(updated)
    dockerfile_path.write_text(updated, encoding="utf-8")


def canonicalize_tasks(
    tasks: list[Path],
    baseline: ModuleType,
    *,
    prefer_canonical: bool = False,
) -> list[Path]:
    if prefer_canonical:
        return [baseline.canonical_task_source(task.resolve()) for task in tasks]
    return [task.resolve() for task in tasks]


def write_bundle(bundle: dict[str, Any], output_root: Path) -> Path:
    bundle_dir = output_root / "shared"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / "goskills_bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return bundle_path


def default_source_bundle(graph_of_skills_root: Path, skillset_name: str | None) -> Path | None:
    candidates: list[Path] = []
    if skillset_name:
        candidates.append(
            graph_of_skills_root
            / "evaluation"
            / "skillsbench"
            / f"generated_table1_{skillset_name}"
            / "shared"
            / "graphskills_bundle.json"
        )
    candidates.append(
        graph_of_skills_root
        / "evaluation"
        / "skillsbench"
        / "generated_table1_skills1000"
        / "shared"
        / "graphskills_bundle.json"
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_or_build_bundle(
    *,
    source_bundle: Path | None,
    graph_of_skills_root: Path,
    skillset_name: str | None,
    skills_root: Path,
    baseline: ModuleType,
) -> dict[str, Any]:
    bundle_path = source_bundle or default_source_bundle(graph_of_skills_root, skillset_name)
    if bundle_path is not None and bundle_path.exists():
        return json.loads(bundle_path.read_text(encoding="utf-8"))
    return baseline.build_graph_bundle(skills_root)


def copy_goskills_runtime(query_dir: Path, bundle_path: Path, baseline: ModuleType) -> None:
    if query_dir.exists():
        shutil.rmtree(query_dir)
    query_dir.mkdir(parents=True, exist_ok=True)
    hardlink_or_copy_file(QUERY_TEMPLATE, query_dir / "query.py", baseline)
    hardlink_or_copy_file(bundle_path, query_dir / "bundle.json", baseline)
    shutil.copytree(GOSKILLS_PACKAGE_DIR, query_dir / "goskills", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def prepare_goskills_task(
    source_task_dir: Path,
    destination_task_dir: Path,
    *,
    bundle_path: Path,
    skills_root: Path,
    baseline: ModuleType,
) -> None:
    baseline.copy_task_tree(source_task_dir, destination_task_dir)
    baseline.replace_task_skills(destination_task_dir, BOOTSTRAP_SKILL_DIR)

    env_dir = destination_task_dir / "environment"
    for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
        hardlink_or_copy_file(TEMPLATE_DIR / name, env_dir / name, baseline)

    (env_dir / "docker-compose.yaml").write_text(
        render_compose_template(
            TEMPLATE_DIR / "docker-compose.yaml",
            destination_env_dir=env_dir,
            skills_root=skills_root,
            baseline=baseline,
        ),
        encoding="utf-8",
    )

    copy_goskills_runtime(env_dir / "goskills", bundle_path, baseline)
    patch_dockerfile(env_dir / "Dockerfile", baseline)


def write_manifest(
    output_root: Path,
    *,
    tasks: list[Path],
    bundle: dict[str, Any],
    graph_of_skills_root: Path,
    skills_root: Path,
    skillset_name: str | None,
    goskills_dir: Path,
) -> None:
    manifest = {
        "graph_of_skills_root": str(graph_of_skills_root),
        "source_tasks_root": str(graph_of_skills_root / "evaluation" / "skillsbench" / "tasks"),
        "skills_root": str(skills_root),
        "skillset_name": skillset_name,
        "task_count": len(tasks),
        "task_ids": [task.name for task in tasks],
        "bundle_metadata": bundle["metadata"],
        "datasets": {
            "goskills": str(goskills_dir),
        },
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate SkillsBench datasets for GoSkills.")
    parser.add_argument("--graph-of-skills-root", type=Path, default=DEFAULT_GRAPH_OF_SKILLS_ROOT)
    parser.add_argument("--skillset-name", default="skills_1000")
    parser.add_argument("--tasks-root", type=Path, default=None)
    parser.add_argument("--skills-root", type=Path, default=None)
    parser.add_argument("--source-bundle", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--task", action="append", default=[])
    parser.add_argument("--max-group-size", type=int, default=3)
    parser.add_argument("--prefer-canonical-tasks", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    graph_of_skills_root = args.graph_of_skills_root.resolve()
    baseline = load_baseline_module(graph_of_skills_root)
    goskills = load_goskills_module()

    tasks_root = (
        args.tasks_root.resolve()
        if args.tasks_root is not None
        else (graph_of_skills_root / "evaluation" / "skillsbench" / "tasks").resolve()
    )
    skills_root = (
        args.skills_root.resolve()
        if args.skills_root is not None
        else (graph_of_skills_root / "data" / "skillsets" / args.skillset_name).resolve()
    )
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    tasks = canonicalize_tasks(
        baseline.build_task_list(tasks_root, args.task),
        baseline,
        prefer_canonical=args.prefer_canonical_tasks,
    )
    bundle = load_or_build_bundle(
        source_bundle=args.source_bundle.resolve() if args.source_bundle is not None else None,
        graph_of_skills_root=graph_of_skills_root,
        skillset_name=args.skillset_name,
        skills_root=skills_root,
        baseline=baseline,
    )
    bundle = goskills.build_group_graph(bundle, max_group_size=args.max_group_size)
    bundle_path = write_bundle(bundle, output_root)

    goskills_dir = output_root / "tasks_goskills"
    baseline.ensure_clean_dir(goskills_dir)
    for task in tasks:
        prepare_goskills_task(
            task,
            goskills_dir / task.name,
            bundle_path=bundle_path,
            skills_root=skills_root,
            baseline=baseline,
        )

    write_manifest(
        output_root,
        tasks=tasks,
        bundle=bundle,
        graph_of_skills_root=graph_of_skills_root,
        skills_root=skills_root,
        skillset_name=args.skillset_name,
        goskills_dir=goskills_dir,
    )
    print(f"Tasks generated: {len(tasks)}")
    print(f"GoSkills dataset: {goskills_dir}")
    print(f"Bundle: {bundle_path}")


if __name__ == "__main__":
    main()
