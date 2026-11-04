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

Follow [DATA.md, step 1](../DATA.md#1-pinned-graph-of-skills-code-and-the-2000-skill-library)
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
These evaluation runners retain their recorded GPT-5.4 model settings.
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

Use a new output directory for each run. The runner stops dispatching on an
invalid trial; it does not automatically retry completed tasks or zero scores.

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
