#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


FIELDS = [
    "job_group",
    "condition",
    "job_name",
    "trial_name",
    "task_name",
    "model_name",
    "reasoning_effort",
    "reward",
    "exception_type",
    "input_tokens",
    "cache_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
    "runtime_sec",
    "environment_setup_sec",
    "agent_setup_sec",
    "agent_execution_sec",
    "verifier_sec",
    "started_at",
    "finished_at",
    "result_path",
]


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def elapsed_seconds(start: str | None, finish: str | None) -> float | None:
    started_at = parse_time(start)
    finished_at = parse_time(finish)
    if not started_at or not finished_at:
        return None
    return round((finished_at - started_at).total_seconds(), 3)


def stage_seconds(result: dict[str, Any], key: str) -> float | None:
    stage = result.get(key) or {}
    return elapsed_seconds(stage.get("started_at"), stage.get("finished_at"))


def trajectory_metrics(result_path: Path) -> dict[str, Any]:
    trajectory = load_json(result_path.parent / "agent" / "trajectory.json")
    final_metrics = trajectory.get("final_metrics") or {}
    extra = final_metrics.get("extra") or {}
    return {
        "reasoning_output_tokens": extra.get("reasoning_output_tokens"),
        "total_tokens": extra.get("total_tokens"),
    }


def path_parts(result_path: Path, jobs_root: Path) -> tuple[str, str, str]:
    relative = result_path.relative_to(jobs_root)
    parts = relative.parts
    return (
        parts[0] if len(parts) > 0 else "",
        parts[1] if len(parts) > 1 else "",
        parts[2] if len(parts) > 2 else "",
    )


def row_from_result(result_path: Path, jobs_root: Path) -> dict[str, Any] | None:
    result = load_json(result_path)
    if not result.get("task_name"):
        return None
    config = result.get("config") or {}
    agent_cfg = config.get("agent") or {}
    agent_kwargs = agent_cfg.get("kwargs") or {}
    agent_result = result.get("agent_result") or {}
    verifier_result = result.get("verifier_result") or {}
    exception_info = result.get("exception_info") or {}
    rewards = verifier_result.get("rewards") or {}
    token_metrics = trajectory_metrics(result_path)
    input_tokens = agent_result.get("n_input_tokens")
    cache_tokens = agent_result.get("n_cache_tokens")
    output_tokens = agent_result.get("n_output_tokens")
    total_tokens = token_metrics.get("total_tokens")
    if total_tokens is None and isinstance(input_tokens, int) and isinstance(output_tokens, int):
        total_tokens = input_tokens + output_tokens
    job_group, condition, job_name = path_parts(result_path, jobs_root)
    return {
        "job_group": job_group,
        "condition": condition,
        "job_name": job_name,
        "trial_name": result.get("trial_name") or result_path.parent.name,
        "task_name": result.get("task_name"),
        "model_name": agent_cfg.get("model_name"),
        "reasoning_effort": agent_kwargs.get("reasoning_effort"),
        "reward": rewards.get("reward"),
        "exception_type": exception_info.get("exception_type") if exception_info else "",
        "input_tokens": input_tokens,
        "cache_tokens": cache_tokens,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": token_metrics.get("reasoning_output_tokens"),
        "total_tokens": total_tokens,
        "runtime_sec": elapsed_seconds(result.get("started_at"), result.get("finished_at")),
        "environment_setup_sec": stage_seconds(result, "environment_setup"),
        "agent_setup_sec": stage_seconds(result, "agent_setup"),
        "agent_execution_sec": stage_seconds(result, "agent_execution"),
        "verifier_sec": stage_seconds(result, "verifier"),
        "started_at": result.get("started_at"),
        "finished_at": result.get("finished_at"),
        "result_path": str(result_path.relative_to(jobs_root)),
    }


def collect(jobs_root: Path, job_glob: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job_group in sorted(jobs_root.glob(job_glob)):
        if not job_group.is_dir():
            continue
        for result_path in sorted(job_group.rglob("result.json")):
            row = row_from_result(result_path, jobs_root)
            if row is not None:
                rows.append(row)
    rows.sort(key=lambda row: (row["task_name"], row["condition"], row["trial_name"]))
    return rows


def write_csv(rows: list[dict[str, Any]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def write_summary(rows: list[dict[str, Any]], output: Path) -> None:
    rewards = [float(row["reward"]) for row in rows if row.get("reward") not in (None, "")]
    runtimes = [float(row["runtime_sec"]) for row in rows if row.get("runtime_sec") not in (None, "")]
    token_rows = [row for row in rows if row.get("total_tokens") not in (None, "")]
    total_tokens = sum(int(row["total_tokens"]) for row in token_rows)
    total_input = sum(int(row["input_tokens"] or 0) for row in token_rows)
    total_output = sum(int(row["output_tokens"] or 0) for row in token_rows)
    errors = [row for row in rows if row.get("exception_type")]
    lines = [
        "# GoSkills SkillBench Metrics Summary",
        "",
        f"- Completed rows: `{len(rows)}`",
        f"- Mean reward: `{mean(rewards):.4f}`" if rewards else "- Mean reward: `n/a`",
        f"- Mean runtime sec: `{mean(runtimes):.3f}`" if runtimes else "- Mean runtime sec: `n/a`",
        f"- Mean total tokens: `{mean([float(row['total_tokens']) for row in token_rows]):.1f}`" if token_rows else "- Mean total tokens: `n/a`",
        f"- Reward rows: `{len(rewards)}`",
        f"- Error rows: `{len(errors)}`",
        f"- Total runtime sec: `{sum(runtimes):.3f}`" if runtimes else "- Total runtime sec: `n/a`",
        f"- Token rows: `{len(token_rows)}`",
        f"- Total input tokens: `{total_input}`",
        f"- Total output tokens: `{total_output}`",
        f"- Total tokens: `{total_tokens}`",
        "",
        "| Task | Reward | Runtime s | Total Tokens | Exception |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['task_name']}` | {row.get('reward') if row.get('reward') not in (None, '') else '-'} | "
            f"{row.get('runtime_sec') if row.get('runtime_sec') not in (None, '') else '-'} | "
            f"{row.get('total_tokens') if row.get('total_tokens') not in (None, '') else '-'} | "
            f"`{row.get('exception_type') or ''}` |"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs-root", type=Path, default=Path("jobs"))
    parser.add_argument("--job-glob", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    rows = collect(args.jobs_root.resolve(), args.job_glob)
    write_csv(rows, args.output.resolve())
    write_summary(rows, args.summary.resolve())
    print(f"Wrote {len(rows)} rows to {args.output}")
    print(f"Wrote summary to {args.summary}")


if __name__ == "__main__":
    main()
