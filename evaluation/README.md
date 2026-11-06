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

Start with [setup](#setup) and [input preparation](../DATA.md).
The methods share the same model settings within each benchmark; each benchmark
retains its own prompts, task interface, and skill-access protocol.

## Setup

Run these commands from the repository root. Full evaluation requires Linux,
Python 3.12, uv, Git, Docker Engine, and Docker Compose v2. Docker must be usable
by your account. TextWorld and hnswlib may also need native build tools; on
Debian/Ubuntu, install `build-essential`, `python3.12-dev`, `libffi-dev`,
`libssl-dev`, `pkg-config`, and `cmake` as needed.

### 1. Install the terminal environment

SkillsBench and Terminal-Bench 2 use Harbor:

```bash
uv venv --python 3.12 --seed .venv-eval
.venv-eval/bin/python -m pip install --upgrade pip setuptools wheel
.venv-eval/bin/python -m pip install \
  -r evaluation/skillsbench/requirements.txt -e '.[terminal]'
.venv-eval/bin/python -m pip check
```

### 2. Install the retrieval environment

Follow [the Graph of Skills dependency setup](../DATA.md#graph-of-skills-dependency)
to obtain the pinned Graph of Skills checkout and install `.venv-retrieval`
with `evaluation/alfworld/requirements.txt`. If already
installed, reuse it.

This environment runs ALFWorld and the upstream skill adapters. Keep the two
environments separate: the terminal requirements pin OpenAI 3.45.0, while the
upstream retrieval requirements pin OpenAI 1.109.1. Reuse environments already
created by this guide. Pass the virtual environment's Python path itself to
runners; resolving its symlink to the system interpreter loses the environment.

### 3. Prepare inputs and configuration

Continue with the benchmark-data and workspace steps in [DATA.md](../DATA.md)
to obtain task datasets and build a GoSkills pool. Copy the local template
once and set its paths to your assets:

```bash
cp evaluation/experiments/configs/local.example.json evaluation/experiments/configs/local.json
```

Relative paths are resolved from the configuration file's directory.
The template selects `.venv-retrieval/bin/python` for upstream retrieval and
ALFWorld. ALFWorld also needs `ALFWORLD_DATA` pointing to its unpacked dataset.
Benchmark-specific external-service credentials, if required by a task, must
be supplied separately.

### 4. Configure providers

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
# For an OpenAI-compatible endpoint only:
# export OPENAI_BASE_URL=https://YOUR-ENDPOINT/v1
export GOS_EMBEDDING_MODEL=openai/text-embedding-3-small
export GOS_EMBEDDING_DIM=1536
```

The launchers read these shell variables; they do not automatically load
`.env`; load a local file with `set -a; . ./.env; set +a` first.
`GOS_LLM_MODEL` configures upstream graph construction, not the benchmark agent.
The benchmark agent model is selected through the shared runtime profile below.
Vector Skills and Graph of Skills need the same embedding model and
dimension as their workspace. GoSkills uses lexical retrieval and needs no
embedding service.

### 5. Check local setup

```bash
.venv-eval/bin/python scripts/doctor.py \
  --config evaluation/experiments/configs/local.json --runtime
```

This checks installed dependencies and local inputs without API requests or
Docker commands. It does not test provider access or run a simulator.


## Model profiles

All three benchmark entrypoints accept the same model options. The default
`--profile gpt54` reads [gpt54.json](experiments/configs/gpt54.json): requested
model `gpt-5.4`, expected response model `gpt-5.4-2026-03-05`, low reasoning,
and a 4,096-token completion limit. Its settings cannot be overridden in place.

For a different OpenAI-compatible chat model, append these options to a
single-task command:

```bash
--profile custom --model YOUR_MODEL --expected-model YOUR_RESPONSE_MODEL
```

`--expected-model` must match the model ID returned by the provider; it defaults
to `--model`. The custom profile omits `reasoning_effort` unless explicitly
selected with `--reasoning-effort low` (or another supported value). Use
`--completion-token-field max_tokens` if your endpoint expects that field
instead of `max_completion_tokens`. The model must support the tools used by
the selected benchmark; these options do not emulate a different API protocol.

For a batch, set the top-level `runtime` block in your local configuration:

```json
"runtime": {
  "profile": "custom",
  "model": "YOUR_MODEL",
  "expected_model": "YOUR_RESPONSE_MODEL",
  "reasoning_effort": null,
  "completion_token_field": "max_completion_tokens"
}
```

One batch uses the same configuration for every selected method. Plans and
receipts record it, and result validation rejects a different response model.
Changing models keeps each benchmark's prompts, retrieval settings, resource
limits and task deadlines. Custom-model runs are separate experiments from the
GPT-5.4 reproduction profile.

## Run a benchmark

From the repository root, configure `evaluation/experiments/configs/local.json`, then print
a run plan:

```bash
.venv-eval/bin/python evaluation/experiments/run.py \
  --config evaluation/experiments/configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all
```

Add `--execute` to run the plan. Execution uses model APIs and, for SkillsBench
and Terminal-Bench 2, Docker. The batch runner selects the appropriate Python
environment and launches a separate process for each trial.

For one benchmark and method:

```bash
.venv-eval/bin/python evaluation/experiments/run.py \
  --config evaluation/experiments/configs/local.json \
  --benchmark tb2 --methods goskills-d \
  --tasks adaptive-rejection-sampler --output runs/tb2-one
```

Use a new output directory for a new campaign. Execution is sequential by
default. To run concurrently, choose both limits before starting:

```bash
.venv-eval/bin/python evaluation/experiments/run.py \
  --config evaluation/experiments/configs/local.json \
  --benchmark all --methods all --workers 4 --per-method 2 \
  --output runs/concurrent --execute
```

`--workers` limits total active trials and `--per-method` limits each method.
Both are bounded at 20; select limits your machine and provider can support.
On an invalid trial, Ctrl-C, or SIGTERM, dispatch stops and active runners drain.
The runner does not automatically retry failed attempts or valid zero scores.

### Resume a campaign

Preview the saved campaign, then add `--execute` to continue only jobs that have
never been dispatched:

```bash
.venv-eval/bin/python evaluation/experiments/run.py \
  --resume --output runs/concurrent
.venv-eval/bin/python evaluation/experiments/run.py \
  --resume --output runs/concurrent --execute
```

Resume uses the saved inputs, code, model and concurrency settings; do not pass
a replacement configuration. Input or source changes are rejected. Completed
receipts and their result artifacts are checked and preserved, including zero
scores. Previous failed attempts remain failed, so a campaign with unresolved
failures does not become complete merely because all queued jobs finish.

A campaign lock is inherited by each runner. If the controller exits abruptly,
resume waits for those runners to exit. A terminal receipt with confirmed
cleanup can then be recovered without executing that task again. An existing
claim without such evidence blocks continuation; inspect its trial and resources
rather than deleting the claim or starting another attempt. Failed trials must
also confirm cleanup before remaining jobs can be dispatched. Resume at the
original campaign path; completed archives can be moved for summarization.

## Summarize your runs

```bash
.venv-eval/bin/python evaluation/analysis/summarize_runs.py runs/gpt54-all \
  --output outputs/gpt54-all-table
```

The summarizer writes `TRIALS.csv`, `SUMMARY.csv`, and `SUMMARY.json` with reward,
input/output tokens, and agent runtime. Incomplete groups retain their missing
count instead of treating missing results as zero. Per-trial outputs include
trajectories, retrieval records, verifier results, and normalized receipts.

## Code structure

```text
evaluation/
├── alfworld_run.py              # ALFWorld entrypoint
├── skill.py                     # Shared five-method skill interface
├── utils.py                     # Shared I/O and provider configuration
├── retrieval.py                 # GoSkills execution-contract adapter
├── assessment.py                # Terminal result and usage validation
├── harbor_base.py               # Shared bash agent and API transport
├── terminal_agent.py            # TB2 agent and retrieval tool
├── alfworld/                    # ALFWorld chat/skill adapters and requirements
├── skillsbench/
│   ├── goskills_benchmark.py     # SkillsBench entrypoint
│   ├── agents/goskills.py        # SkillsBench agent
│   ├── task_pack.py             # Task preparation and Harbor configuration
│   ├── bridge.py                # Agent-facing retrieval command parsing
│   ├── query.py                 # Host retrieval helper
│   └── requirements.txt         # Shared Harbor environment (also used by TB2)
├── terminalbench2/
│   ├── terminalbench2_benchmark.py
│   └── config.py                # Original task resources and deadlines
├── experiments/
│   ├── run.py                   # Three-benchmark, five-method batch runner
│   └── configs/                 # Task membership and local path template
└── analysis/
    └── summarize_runs.py        # Scores, tokens, runtime, and missing counts
```

Install this repository in both Python environments before using these entrypoints.
The evaluation code is installed as `goskills_eval`; the separate Graph of Skills
checkout keeps its own `evaluation` package. This avoids mixing the two projects'
ALFWorld runners and skill interfaces. The original ALFWorld prompts, simulator
configuration, and SkillsBench method templates are read from the pinned upstream
checkout described in [DATA.md](../DATA.md).
