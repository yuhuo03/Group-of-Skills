<h1 align="center">[NeurIPS '26] Group of Skills (GoSkills)</h1>

<p align="center">
  <strong>Group-Structured Skill Retrieval for Agent Skill Libraries</strong>
</p>

<p align="center">
  <strong>Kun Zeng</strong><sup>*</sup> &middot;
  <a href="https://github.com/yuhuo03"><strong>Yu Huo</strong></a><sup>*</sup> &middot;
  <strong>Siyu Zhang</strong> &middot;
  <strong>Zi Ye</strong> &middot;
  <strong>Yuecheng Zhuo</strong> &middot;
  <strong>Haoyue Liu</strong> &middot;
  <strong>Yuquan Lu</strong> &middot;
  <strong>Junhao Wen</strong> &middot;
  <strong>Xiaoying Tang</strong><sup>†</sup>
</p>

<p align="center">
  <a href="https://huggingface.co/datasets/DLPenn/graph-of-skills-data"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20HuggingFace-Skill_Library-yellow" alt="Skill library"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10--3.12-3776ab?logo=python&logoColor=white" alt="Python"></a>
</p>

---

## 🔥 Updates

- **[2026-11-04]** Released the **GPT-5.4 implementation** and five-method evaluation scripts for SkillsBench, ALFWorld, and Terminal-Bench 2 — see [Evaluation](#evaluation).
- **[2026-09-25]** Paper available on [OpenReview](https://openreview.net/forum?id=MmJBYf16Bn).
- **[2026-09-24]** 🎉 **Group of Skills is accepted to NeurIPS 2026 (Poster)!**
- **[2026-05-06]** Initial code release on [GitHub](https://github.com/yuhuo03/Group-of-Skills).

---

## Overview

GoSkills builds **anchor-centered skill groups** offline from a typed skill graph,
then retrieves a compact **group plan** at task time. The plan combines the task's
anchor skill with relevant support and checking skills, prunes incompatible
choices, and presents bounded source instructions to the agent. GoSkills builds
on the [Graph of Skills](https://github.com/davidliuk/graph-of-skills) data and
benchmark stack.

<p align="center">
  <img src="assets/comparison.png" alt="Comparison of Vanilla Skills, Vector Skills, Graph of Skills, and Group of Skills" width="800">
</p>

## How It Works

<p align="center">
  <img src="assets/framework.png" alt="GoSkills pipeline: Offline Group Construction → Group Selection → Bounded Execution Contract" width="800">
</p>

**Retrieval pipeline:**

1. **Seed** -- retrieve lexical candidate skills for the visible task query.
2. **Group** -- activate reusable anchor-centered groups and their supporting relations.
3. **Prune** -- remove incompatible or low-gain choices under group and context budgets.
4. **Return** -- emit a bounded execution contract and source-preserving skill payloads.

The returned plan identifies where to start, which support and checking skills to
use, and visible requirement cues not covered by the presented skill text. See
[the method guide](goskills/README.md) for the graph schema and retrieval settings.

## Citation

If you find this work useful, please cite:

```bibtex
@software{zeng2026goskills,
  title   = {Group of Skills: Group-Structured Skill Retrieval for Agent Skill Libraries},
  author  = {Zeng, Kun and Huo, Yu and Zhang, Siyu and Ye, Zi and Zhuo, Yuecheng and
             Liu, Haoyue and Lu, Yuquan and Wen, Junhao and Tang, Xiaoying},
  year    = {2026},
  version = {0.2.0rc2},
  url     = {https://github.com/yuhuo03/Group-of-Skills}
}
```

<sup>*</sup> Equal contribution. <sup>†</sup> Corresponding author.

## Installation

### Requirements

- Python 3.10 -- 3.12 for core retrieval (Python 3.12 recommended)
- Git
- [`uv`](https://docs.astral.sh/uv/) for virtual environments; `pip` for package installation
- Linux, Python 3.12, Docker Engine and Docker Compose v2 for full benchmark runs
- An OpenAI-compatible API key for benchmark agents and embedding-backed baselines

### Setup

```bash
git clone https://github.com/yuhuo03/Group-of-Skills.git
cd Group-of-Skills
uv venv --python 3.12 --seed .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pip check
```

Core build/query needs no API key. For benchmark runs, configure the shell
variables below and follow [the evaluation setup](evaluation/SETUP.md) to install
the separate terminal and retrieval environments.

<details>
<summary><strong>Provider: OpenAI (direct)</strong></summary>

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
unset OPENAI_BASE_URL
export GOS_EMBEDDING_MODEL=openai/text-embedding-3-small
export GOS_EMBEDDING_DIM=1536
```

These are shell variables. The launchers do not automatically load `.env`.
GoSkills retrieval uses lexical seeds and makes no embedding calls.

</details>

<details>
<summary><strong>Provider: OpenAI-compatible endpoint</strong></summary>

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
export OPENAI_BASE_URL=https://YOUR-ENDPOINT/v1
export GOS_EMBEDDING_MODEL=openai/text-embedding-3-small
export GOS_EMBEDDING_DIM=1536
```

The endpoint must support the configured chat model and, for Vector / Graph of
Skills, the same embedding model used to construct the workspace.

</details>

## Quick Start

**Goal:** install the package, obtain the skill library and a compatible graph,
build a group pool, then retrieve an execution contract from the shell.

**Read next:** [DATA.md](DATA.md) for pinned assets and index construction;
[`.env.example`](.env.example) for provider variables. After retrieval works,
use [evaluation/README.md](evaluation/README.md) for the benchmark runners.

### Step 0: Install (once per machine)

Complete [Installation](#installation) above. No provider is needed for the small
included example. For real benchmark assets, set up the two Python environments
as described in [the evaluation setup](evaluation/SETUP.md) and [DATA.md](DATA.md).

### Step 1: Download skill libraries

The experimental **2,000-skill library** is hosted on
[HuggingFace](https://huggingface.co/datasets/DLPenn/graph-of-skills-data), not in git.
Download and verify the pinned archive:

```bash
python scripts/fetch_asset.py \
  --url https://huggingface.co/datasets/DLPenn/graph-of-skills-data/resolve/83a8c59f6d09b849e57a50ed2577e253995d257e/skills_2000.tar.gz \
  --sha256 9a616f600488341263f4e931c8387140eb06349a957d498d98a5f5be90109a89 \
  --output data/external/skills_2000 --execute
```

**Tiny smoke test without a download:** use `assets/examples/minimal_graph.json`, a
synthetic graph included with the repository.

### Step 2: Workspace directory layout (recommended for benchmarks)

Use the same source library, directed workspace, and group pool across the
corresponding retrieval methods. The example configuration expects:

| Asset | Recommended path |
|-------|------------------|
| Skill library | `data/external/skills_2000/` |
| Pinned Graph of Skills checkout | `data/external/graph-of-skills/` |
| Typed directed workspace | `data/external/workspace/` |
| Exported source graph | `data/external/native-graph.json` |
| GoSkills group pool | `data/external/pool.json` |

### Step 3: Get a workspace (choose one path)

**A. Build for the full library:** follow [DATA.md](DATA.md) to construct a typed
directed GoS workspace and export its source graph. Index construction calls APIs;
building the GoSkills group pool from an exported graph is local:

```bash
python -m goskills build \
  --graph data/external/native-graph.json \
  --output data/external/pool.json
```

**B. Start with the included example** (no API or downloads):

```bash
DEMO_DIR=$(mktemp -d)
python -m goskills build \
  --graph assets/examples/minimal_graph.json --output "$DEMO_DIR/pool.json"
```

> **Compatibility note:** use a typed directed source graph from the pinned GoS
> checkout. Older undirected `*_v1` workspaces cannot substitute for it. See
> [DATA.md](DATA.md) for the exact commit and export requirements.

### Step 4: Retrieve

For the example from Step 3B:

```bash
python -m goskills query --pool "$DEMO_DIR/pool.json" \
  --query "Parse STL and produce JSON with unit tests." \
  --output-json "$DEMO_DIR/answer.json"
```

For the full library, replace the pool path with `data/external/pool.json` and use
a fresh output path. The default output is the bounded execution contract.

### Step 5: Inspect or extend

```bash
python -m goskills validate-bundle "$DEMO_DIR/answer.json"
python -m goskills query --pool "$DEMO_DIR/pool.json" \
  --query "Parse STL and produce JSON with unit tests." --json
```

The JSON bundle contains selected groups, skill payloads, source spans, selection
traces, and coverage debt. To extend the source graph, build a new pool at a new
output path. Pools and saved bundles are not overwritten. See
[Agent Integration](#agent-integration) for the Python API.

### Step 6: What to run next

- **End-to-end sanity check** (one task): see the **Minimal Verification** collapsible in [Evaluation](#evaluation).
- **Paper benchmarks** (all three benchmarks and five methods): [evaluation/README.md](evaluation/README.md).

## Agent Integration

### Python / CLI

An agent can call the retrieval CLI or use the same core through Python:

```python
from goskills.config import validate_config
from goskills.groups import build_pool
from goskills.io import read_json
from goskills.retrieval import Retriever
from goskills.validation import validate_bundle

pool = build_pool(read_json("assets/examples/minimal_graph.json"), validate_config())
bundle = Retriever(pool).query("Parse STL and produce JSON with unit tests.")
validate_bundle(bundle)
print(bundle["rendered_context"])
```

**Available interfaces:**

| Interface | Purpose |
|-----------|---------|
| `build_pool` | Construct reusable groups from a typed graph |
| `Retriever.query` | Retrieve an execution contract and source skill payloads |
| `validate_bundle` | Verify rendered context, budgets, and coverage debt |
| `python -m goskills` | Use the build/query/validate workflow from the shell |

### Docker / Container (SkillsBench)

The SkillsBench adapter exposes an agent-facing retrieval command inside the
benchmark interaction:

```bash
goskills-query "parse binary STL file and calculate mass"
```

The bash adapter dispatches this query to the host retriever and returns the
bounded contract. Source paths refer to the skill library mounted at
`/opt/graphskills/skills`. The other retrieval conditions use `vectorskills-query`
and `graphskills-query`. See [SkillsBench evaluation](evaluation/skillsbench/README.md)
for task preparation and container integration.

## CLI Reference

| Command | Description |
|---------|-------------|
| `goskills export-native` | Export the pinned compatible GoS workspace as a typed source graph |
| `goskills build` | Build a reusable group pool from a source graph |
| `goskills query` | Retrieve a bounded skill bundle and execution contract |
| `goskills validate-bundle` | Validate bundle integrity, context budgets, and coverage debt |
| `goskills-query` | Agent-facing retrieval inside the SkillsBench bash adapter |
| `.venv-eval/bin/python scripts/run_benchmark.py` | Plan or execute benchmark/method combinations |
| `.venv-eval/bin/python scripts/summarize_runs.py` | Aggregate per-trial scores, tokens, and runtime |

## Configuration

Provider variables are documented in [`.env.example`](.env.example). Evaluation
asset paths are set in [evaluation/configs/local.example.json](evaluation/configs/local.example.json).
GoSkills uses the following default settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `seed_mode` | `lexical` | Query-visible lexical seeding |
| `seed_top_k` | `4` | Initial candidate skills |
| `top_n` | `4` | Maximum presented skills |
| `max_context_chars` | `9000` | Full rendered-context character cap |
| Skill body cap | `1800` | Maximum characters per source skill |
| Members per group | `3` | Offline group-size cap |
| Selected groups | `3` | Online group-selection cap |

See [Method](goskills/README.md) for exact policy fields and validation rules.

> **Note:** Vector and Graph of Skills must use the same embedding model and
> dimension at retrieval time as at index construction.

## Evaluation

**Docs:** Start with [evaluation/README.md](evaluation/README.md) for the five
methods and benchmark entrypoints. The complete environment setup is in
[the evaluation setup guide](evaluation/SETUP.md); task and index preparation
are in [DATA.md](DATA.md).

We evaluate GoSkills on three benchmarks:

| Benchmark | Type | Tasks |
|-----------|------|-------|
| **ALFWorld** | Interactive household tasks | 134 episodes |
| **SkillsBench** | Dockerized coding tasks | 86 tasks |
| **Terminal-Bench 2** | Dockerized terminal tasks | 89 tasks |

All support `noskills`, `vanilla`, `vector`, `native-gos`, and `goskills-d`.
After preparing the inputs, configure and run the shared launcher:

```bash
cp evaluation/configs/local.example.json evaluation/configs/local.json
.venv-eval/bin/python scripts/doctor.py --config evaluation/configs/local.json --runtime

# Plan all 15 combinations without calling a provider.
.venv-eval/bin/python scripts/run_benchmark.py --config evaluation/configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all

# Execute the plan as a new run (billable API calls and benchmark environments).
.venv-eval/bin/python scripts/run_benchmark.py --config evaluation/configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all --execute

.venv-eval/bin/python scripts/summarize_runs.py runs/gpt54-all --output outputs/gpt54-all-table
```

Use a fresh output directory for each run. The launcher preserves completed
records and stops dispatch on infrastructure or incomplete-verifier failures.
A valid zero score remains zero; missing results remain missing.

<details>
<summary><strong>Minimal Verification (end-to-end smoke test)</strong></summary>

**Scope:** one GoSkills task on Terminal-Bench 2. This is a setup check, not a full
benchmark sweep. The commands below invoke APIs only when `--execute` is added.

**Prerequisites:**

- Both Python environments and the original datasets from [DATA.md](DATA.md).
- A compatible full-library workspace and GoSkills group pool.
- Docker running and `OPENAI_API_KEY` exported in the shell.
- `evaluation/configs/local.json` populated with the local asset paths.

**1. Validate local inputs**

```bash
.venv-eval/bin/python scripts/doctor.py --config evaluation/configs/local.json --runtime
```

**2. Preview one task**

```bash
.venv-eval/bin/python scripts/run_benchmark.py --config evaluation/configs/local.json \
  --benchmark tb2 --methods goskills-d --tasks adaptive-rejection-sampler \
  --output runs/tb2-one
```

**3. Run and summarize the task**

```bash
.venv-eval/bin/python scripts/run_benchmark.py --config evaluation/configs/local.json \
  --benchmark tb2 --methods goskills-d --tasks adaptive-rejection-sampler \
  --output runs/tb2-one --execute
.venv-eval/bin/python scripts/summarize_runs.py runs/tb2-one --output outputs/tb2-one
```

**4. What "success" looks like**

- The run produces `PLAN.json`, `STATUS.json`, and a per-trial result receipt.
- The summary reports one completed trial and its score, token usage, and runtime.
- A complete verifier result may legitimately score zero. A transport or
  environment failure is recorded separately and is not converted to zero.

</details>

## Repository Layout

```
Group-of-Skills/
├── assets/                      # Method figures and a small tutorial graph
├── evaluation/                  # Three benchmarks and five methods
│   ├── alfworld/                #   ALFWorld runner
│   ├── skillsbench/             #   SkillsBench / Harbor integration
│   ├── terminalbench2/          #   Terminal-Bench 2 / Harbor integration
│   ├── goskills_eval/           #   Shared evaluation adapters
│   ├── configs/                 #   Task manifests and local configuration
│   └── requirements/            #   Separate evaluation dependency sets
├── goskills/                    # Group construction, retrieval and CLI
├── scripts/                     # Asset preparation and evaluation utilities
├── tests/                       # Offline tests
├── .env.example                 # Provider configuration template
├── pyproject.toml               # Package definition
├── CONTRIBUTING.md              # Development guide
└── DATA.md                      # External data and workspace setup
```

## Documentation

| Document | What it covers |
|----------|----------------|
| [DATA.md](DATA.md) | Skill library, benchmark inputs and workspace preparation |
| [goskills/README.md](goskills/README.md) | Group construction, retrieval and graph schema |
| [evaluation/SETUP.md](evaluation/SETUP.md) | Evaluation dependencies and configuration |
| [evaluation/README.md](evaluation/README.md) | Three benchmarks and five methods |
| [evaluation/skillsbench/README.md](evaluation/skillsbench/README.md) | SkillsBench |
| [evaluation/alfworld/README.md](evaluation/alfworld/README.md) | ALFWorld |
| [evaluation/terminalbench2/README.md](evaluation/terminalbench2/README.md) | Terminal-Bench 2 |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development setup and tests |

## License

A project license has not yet been specified. Third-party components and datasets
retain their own licenses; see [DATA.md](DATA.md#attribution).
