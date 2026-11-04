# Evaluation

GoSkills provides runners for three benchmarks and five methods.

| Benchmark | Runner | Environment |
|---|---|---|
| SkillsBench | [SkillsBench guide](skillsbench/README.md) | `.venv-eval` |
| ALFWorld | [ALFWorld guide](alfworld/README.md) | `.venv-retrieval` |
| Terminal-Bench 2 | [Terminal-Bench 2 guide](terminalbench2/README.md) | `.venv-eval` |

| Method | CLI identifier |
|---|---|
| No Skills | `noskills` |
| Vanilla Skills | `vanilla` |
| Vector Skills | `vector` |
| Graph of Skills | `native-gos` |
| GoSkills | `goskills-d` |

Start with [environment setup](SETUP.md) and [input preparation](../DATA.md).
The methods share the same model settings within each benchmark; each benchmark
retains its own prompts, task interface, and skill-access protocol.

## Run a benchmark

From the repository root, configure `evaluation/configs/local.json`, then print
a run plan:

```bash
.venv-eval/bin/python scripts/run_benchmark.py \
  --config evaluation/configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all
```

Add `--execute` to run the plan. Execution uses model APIs and, for SkillsBench
and Terminal-Bench 2, Docker. The batch runner selects the appropriate Python
environment and launches a separate process for each trial.

For one benchmark and method:

```bash
.venv-eval/bin/python scripts/run_benchmark.py \
  --config evaluation/configs/local.json \
  --benchmark tb2 --methods goskills-d \
  --tasks adaptive-rejection-sampler --output runs/tb2-one
```

Use a new output directory for each run. The runner stops dispatching on an
invalid trial; it does not automatically retry completed tasks or zero scores.

## Summarize your runs

```bash
.venv-eval/bin/python scripts/summarize_runs.py runs/gpt54-all \
  --output outputs/gpt54-all-table
```

The summarizer writes `TRIALS.csv`, `SUMMARY.csv`, and `SUMMARY.json` with reward,
input/output tokens, and agent runtime. Incomplete groups retain their missing
count instead of treating missing results as zero. Per-trial outputs include
trajectories, retrieval records, verifier results, and normalized receipts.
