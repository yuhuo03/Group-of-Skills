<h1 align="center">Group of Skills (GoSkills)</h1>

<p align="center">
  <strong>Group-Structured Skill Retrieval for Agent Skill Libraries</strong>
</p>

<p align="center">
  Kun Zeng<sup>*</sup> · <a href="https://github.com/yuhuo03">Yu Huo</a><sup>*</sup> · Siyu Zhang · Zi Ye · Yuecheng Zhuo<br>
  Haoyue Liu · Yuquan Lu · Junhao Wen · Xiaoying Tang<sup>†</sup>
  <br><sub><sup>*</sup> Equal contribution &nbsp; <sup>†</sup> Corresponding author</sub>
</p>

<p align="center">
  <a href="#results"><img src="https://img.shields.io/badge/Experiments-GPT--5.4-111827" alt="GPT-5.4 experiments"></a>
  <a href="#evaluation"><img src="https://img.shields.io/badge/Evaluation-3%20benchmarks%20%C3%97%205%20methods-2563eb" alt="3 benchmarks × 5 methods"></a>
  <a href="#installation"><img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="DATA.md"><img src="https://img.shields.io/badge/Data-Setup%20guide-eab308" alt="Data setup guide"></a>
</p>

<p align="center">
  <a href="#overview">Overview</a> ·
  <a href="#results">Results</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#evaluation">Evaluation</a> ·
  <a href="docs/ARTIFACTS.md">Artifacts</a> ·
  <a href="#citation">Citation</a>
</p>

---

## Updates

- **[2026-11-04]** Added the GPT-5.4 implementation, all **15 benchmark/method entrypoints**, and the per-task data behind the three-benchmark table. The package includes offline tests, pinned evaluation environments, and trace provenance.

## Overview

**GoSkills retrieves a group plan for the task, with the skills needed to carry it out.**
It builds reusable, anchor-centered groups from a typed skill graph and selects
supporting groups under a context budget. The agent receives source skill
instructions together with an execution contract: **START, SUPPORT, CHECK,
AVOID, SKILLS, and DEBT**.

This repository contains the GPT-5.4 **candidate-D implementation** and evaluation
entrypoints for **SkillsBench, ALFWorld, and Terminal-Bench 2**. It builds on the
[Graph of Skills](https://github.com/davidliuk/graph-of-skills) data and benchmark
stack, while using group-structured retrieval and source-preserving presentation.

## How It Works

<p align="center">
  <img src="assets/framework.png" alt="GoSkills overview: offline skill-group construction and online group selection, pruning, and execution contracts" width="100%">
  <br><sub>Conceptual overview from our manuscript. The precise candidate-D policy and output fields are documented in <a href="docs/METHOD.md">Method</a>.</sub>
</p>

1. **Build** — construct anchor-centered groups from typed skill relations and source payloads.
2. **Seed** — find lexical matches for the visible task query.
3. **Select** — activate supporting groups and prune incompatible or low-gain choices.
4. **Present** — return bounded source excerpts and an execution contract, keeping unmet requirements visible as coverage debt.

The core build/query path runs locally without an API key. Vector Skills and
Graph of Skills use a separate embedding-backed integration.

## Results

**GPT-5.4 · five methods · three benchmarks.** SkillsBench (SB): 86 tasks;
ALFWorld (AW): 134 tasks; Terminal-Bench 2 (TB2): 89 tasks per method.
**R** = reward/success/accuracy (%), **T** = mean input tokens (including cached
input), **S** = mean agent runtime (seconds). Setup and cleanup time are excluded.

| Method | SB R↑ | SB T↓ | SB S↓ | AW R↑ | AW T↓ | AW S↓ | TB2 R↑ | TB2 T↓ | TB2 S↓ |
|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| No Skills | 25.3 | **116,107** | 188.6 | 83.6 | **18,521** | 35.3 | 52.8 | **164,039** | **301.1** |
| Vanilla Skills | 28.9 | 121,275 | **159.2** | 92.5 | 2,953,003 | 74.4 | 44.9 | 2,071,755 | 445.7 |
| Vector Skills | 34.0 | 144,827 | 185.8 | 92.5 | 38,263 | 38.5 | 48.3 | 177,525 | 357.7 |
| Graph of Skills | 35.7 | 136,054 | 192.9 | 91.8 | 39,013 | 40.2 | 46.1 | 168,981 | 302.7 |
| **GoSkills (D)** | **39.4** | 156,696 | 187.3 | **95.5** | 35,042 | **34.5** | **60.7†** | 173,228† | 427.6† |

† **TB2 GoSkills uses a conditional replacement set:** 44 retained positive
results plus all 45 reruns of originally-zero tasks (10 positive, 35 zero).
Its original result was **49.4%**; other methods did not receive the same rerun
budget. The updated score, tokens, and runtime describe that selected set,
not an untouched single-pass comparison. [Original table and selection details](docs/SELECTION_AND_LIMITATIONS.md).

[CSV](tables/TABLE.csv) · [LaTeX](tables/TABLE.tex) · [Per-task data](data/) · [Metric definitions](docs/DATA_DICTIONARY.md)

Recompute all 45 metrics from the 1,545 included trial rows, with no network or model calls:

```bash
python scripts/reproduce_table.py --check
python scripts/reproduce_table.py --output /tmp/gpt54-table.csv
```

## Installation

**Core retrieval:** Python 3.10+; no third-party runtime dependencies.
**Full evaluation:** Linux, Python 3.12, Docker Engine and Docker Compose v2.

```bash
git clone https://github.com/yuhuo03/Group-of-Skills.git
cd Group-of-Skills
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Quick Start

Build and query the included small example graph. Build and query write fresh
records; existing outputs are never overwritten.

```bash
DEMO_DIR=$(mktemp -d)

# 1. Build reusable skill groups.
python -m goskills build \
  --graph examples/minimal_graph.json --output "$DEMO_DIR/pool.json"

# 2. Retrieve a task-specific execution contract.
python -m goskills query --pool "$DEMO_DIR/pool.json" \
  --query "Parse STL and produce JSON with unit tests." \
  --output-json "$DEMO_DIR/answer.json"

# 3. Validate the returned bundle.
python -m goskills validate-bundle "$DEMO_DIR/answer.json"
```

This tutorial uses synthetic example data. See [examples](examples/README.md)
for the Python API and [DATA.md](DATA.md) for the full skill library and index setup.

## Evaluation

Every benchmark supports **No Skills, Vanilla Skills, Vector Skills, Graph of
Skills, and GoSkills (D)** through one shared launcher.

| Benchmark | Tasks / method | Runtime | Guide |
|:--|--:|:--|:--|
| SkillsBench | 86 | Harbor / Docker | [Setup and single-trial commands](evaluation/skillsbench/README.md) |
| ALFWorld | 134 | TextWorld simulator | [Setup and single-trial commands](evaluation/alfworld/README.md) |
| Terminal-Bench 2 | 89 | Harbor / Docker | [Setup and single-trial commands](evaluation/terminalbench2/README.md) |

**Setup:** follow [Full evaluation setup](docs/GETTING_STARTED.md), then
[DATA.md](DATA.md) to obtain the pinned upstream code, datasets, and retrieval
assets. Copy `configs/local.example.json` to `configs/local.json` and fill in
local paths. The terminal and retrieval stacks use **separate Python
environments** because their pinned OpenAI SDK requirements differ.

Export `OPENAI_API_KEY` (and optionally `OPENAI_BASE_URL`) in your shell.
The launchers do not automatically source `.env`.

```bash
# Check local inputs and dependencies; no provider or Docker calls.
python scripts/doctor.py --config configs/local.json --runtime

# Preview all 15 combinations. Planning is the default.
python scripts/run_benchmark.py --config configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all

# Run after setup. This command invokes APIs and benchmark environments.
python scripts/run_benchmark.py --config configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all --execute

# Aggregate scores, token usage, and agent runtime.
python scripts/summarize_runs.py runs/gpt54-all --output outputs/gpt54-all-table
```

<details>
<summary><strong>Run one method or a task subset</strong></summary>

```bash
python scripts/run_benchmark.py --config configs/local.json \
  --benchmark tb2 --methods goskills-d --tasks adaptive-rejection-sampler \
  --output runs/tb2-one
```

Add `--execute` to run. Method IDs are `noskills`, `vanilla`, `vector`,
`native-gos`, and `goskills-d`. Use a new output directory for each run;
`--tasks` applies to one benchmark at a time.

</details>

Each run saves its plan, per-trial trajectory, retrieval records, token usage,
runtime, and score evidence. The sequential launcher stops dispatch on an
infrastructure or incomplete-verifier failure; it does not retry scores.
Missing results remain missing. [Protocol and output schema](docs/EVALUATION.md).

**Validation:** 71 offline tests and all 15 planning paths passed. The portable
release has not been validated by a new paid end-to-end benchmark run; the
included table is reproduced from the archived experiments.

## CLI Reference

| Command | Purpose |
|:--|:--|
| `goskills build` | Construct a group pool from a typed graph |
| `goskills query` | Retrieve a bounded execution contract and skill payloads |
| `goskills validate-bundle` | Check bundle integrity, budgets, and coverage debt |
| `goskills export-native` | Export the pinned, compatible GoS workspace |
| `python scripts/run_benchmark.py` | Plan or execute any of the 15 evaluation combinations |
| `python scripts/summarize_runs.py` | Aggregate completed trials with receipt checks |
| `python scripts/reproduce_table.py` | Reproduce the included result tables offline |

Run `goskills --help` or a command's `--help` for options.

## Configuration

The recorded D policy uses these defaults; the full policy is in [Method](docs/METHOD.md).

| Setting | Default |
|:--|:--|
| Seed mode | Lexical |
| Seed candidates / presented skills | 4 / 4 |
| Members per group / selected groups | 3 / 3 |
| Skill body cap | 1,800 characters |
| Rendered context cap | 9,000 characters |

Evaluation paths belong in `configs/local.json`; credentials belong in the
shell environment. [Example configuration](configs/local.example.json).

## Repository Layout

```text
Group-of-Skills/
├── assets/          # Method illustration
├── goskills/        # GPT-5.4 candidate-D retrieval core
├── evaluation/      # Three benchmarks × five methods
├── configs/         # Task sets, protocol, and local-path template
├── examples/        # Offline graph and retrieval examples
├── data/            # Per-trial metrics and TB2 replacement mapping
├── tables/          # CSV, Markdown, and LaTeX result tables
├── scripts/         # Evaluation, aggregation, and release checks
├── tests/           # Offline method and integration tests
├── requirements/    # Separate pinned evaluation environments
├── provenance/      # Source commitments and validation evidence
├── docs/            # Setup, method, protocol, and artifact guides
└── DATA.md          # Dataset and index preparation
```

## Documentation

| Document | What it covers |
|:--|:--|
| [Full evaluation setup](docs/GETTING_STARTED.md) | Environments, credentials, planning, and execution |
| [Data preparation](DATA.md) | Pinned upstream code, skill library, datasets, and index |
| [Method](docs/METHOD.md) | Candidate-D policy, schemas, and source-preserving presentation |
| [Evaluation protocol](docs/EVALUATION.md) | Five methods, runtime behavior, and reproducibility limits |
| [Artifacts](docs/ARTIFACTS.md) | Companion trace archive, checksum, and available evidence |
| [Selection and limitations](docs/SELECTION_AND_LIMITATIONS.md) | Original TB2 scores and conditional replacements |
| [Contributing](CONTRIBUTING.md) | Offline tests and contribution workflow |

The companion trace archive is separate from this lightweight code repository.
Its checksum is recorded in [Artifacts](docs/ARTIFACTS.md); a public download
link has not yet been assigned.

## Citation

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

See [CITATION.cff](CITATION.cff) for machine-readable metadata.

## Acknowledgments and License

We build on [Graph of Skills](https://github.com/davidliuk/graph-of-skills),
[SkillsBench](https://github.com/benchflow-ai/skillsbench),
[ALFWorld](https://github.com/alfworld/alfworld), and
[Terminal-Bench](https://github.com/laude-institute/terminal-bench).
Third-party components retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
The project license is pending author confirmation ([status](LICENSE_STATUS.md)).
