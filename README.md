# GoSkills: Group-Structured Skill Retrieval

This repository contains the anonymous code artifact for **Group of Skills (GoSkills)**, an inference-time method for group-structured retrieval over agent skill libraries. GoSkills changes the agent-facing retrieval unit from a flat list of atomic skills to a compact, role-labeled execution context with an anchor group, support expansion, visible checks, conflict pruning, and a bounded set of presented skill payloads.

The downstream agent, skill payloads, and task environment are left unchanged. Only the retrieved skill context differs.

## Repository Layout

```text
goskills/                     Core GoSkills implementation
  group_graph.py              Offline construction of anchor-centered groups and the group graph H
  retrieval.py                Query-time group activation, expansion, bottlenecking, and rendering
  text.py                     Tokenization, weighting, and deterministic query decomposition
  cli.py                      Build/query command line interface

gos/core/parsing.py           Minimal SKILL.md parser used by benchmark data builders
skills/goskills-retriever/    Bootstrap skill exposed inside benchmark tasks

evaluation/skillsbench/       Benchmark generation and execution helpers
  gen_benchmark.py            Builds GoSkills SkillsBench task directories
  agent.py                    OpenAI-compatible direct API benchmark agent
  collect_metrics.py          Aggregates Harbor result files
  goskills_assets/query.py    Container-local goskills-query entry point
  prompt_templates/           Benchmark prompt template
  _goskills_template/         Files injected into task containers

evaluation/alfworld/          Lightweight ALFWorld GoSkills selector hook

scripts/
  download_data.sh            Downloads public benchmark assets
  run_eval.sh                 Runs GoSkills with an OpenAI-compatible model
  run_eval_cc.sh              Same runner with a Claude-style default model name
  check_release.sh            Runs tests, syntax checks, default checks, and anonymity scans

tests/test_goskills.py        Unit-level smoke tests
```

## Installation

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
```

The core `goskills` package has only lightweight Python dependencies. Full benchmark execution additionally requires Docker, the SkillsBench/Harbor runtime used by the Graph of Skills benchmark code, the ALFWorld environment for ALFWorld runs, and an OpenAI-compatible API endpoint.

## Quick Smoke Test

```bash
pytest -q
```

Expected result:

```text
4 passed
```

You can also run the core algorithm without downloading benchmark data:

```bash
python - <<'PY'
from goskills.group_graph import build_group_graph
from goskills.retrieval import retrieve

bundle = {
    "metadata": {"name": "minimal"},
    "skills": [
        {"name": "csv-cleaner", "description": "Clean and normalize CSV tables.", "inputs": ["csv"], "outputs": ["csv"]},
        {"name": "schema-verifier", "description": "Validate output schema and row counts.", "inputs": ["csv"], "outputs": ["test report"]},
        {"name": "xlsx-export", "description": "Export CSV tables to Excel workbooks.", "inputs": ["csv"], "outputs": ["xlsx"]},
    ],
    "edges": [
        {"source": "csv-cleaner", "target": "schema-verifier", "type": "workflow", "weight": 0.9}
    ],
}

bundle = build_group_graph(bundle)
result = retrieve(bundle, "clean csv data and verify output schema", top_n=4)
print(result["summary"])
PY
```

## Build and Query GoSkills

The input bundle format is a JSON object with `metadata`, `skills`, and `edges`. The output bundle adds GoSkills group metadata under the internal `group_graph` field.

```bash
python -m goskills.cli build \
  --bundle path/to/source_bundle.json \
  --output path/to/goskills_bundle.json

python -m goskills.cli query \
  "recover xlsx cells and verify schema" \
  --bundle path/to/goskills_bundle.json \
  --top-n 4
```

After installation, the same query interface is available as:

```bash
goskills-query "recover xlsx cells and verify schema" --bundle path/to/goskills_bundle.json
```

## Paper Defaults

The released defaults match the fixed configuration described in the paper: lexical seeds, `seed-top-k=4`, `top-n=4`, max group size 3, at most 3 selected groups, at most 2 coverage backfill skills, max skill payload 1800 characters, and max rendered context 9000 characters. The rendered context exposes the execution contract as `Start`, `Support`, `Check`, `Avoid`, `Debt`, and `Skills`.

Run the release check before packaging or pushing:

```bash
./scripts/check_release.sh
```

## Public Data Assets

The benchmark scripts expect two external assets:

- skill libraries under `data/skillsets/`
- SkillsBench task definitions under `evaluation/skillsbench/tasks/`

Download them with:

```bash
./scripts/download_data.sh --all
```

By default, the script fetches skill-set archives from `DLPenn/graph-of-skills-data` on HuggingFace and task definitions from `benchflow-ai/skillsbench` on GitHub. Override the dataset source with `GOS_HF_REPO` when needed.

## SkillsBench Benchmark

The full benchmark reuses the SkillsBench/Harbor runtime used by Graph of Skills. Set the path to that checkout explicitly:

```bash
export GRAPH_OF_SKILLS_ROOT=/path/to/graph-of-skills
export OPENAI_API_KEY=...
export OPENAI_BASE_URL=https://api.openai.com/v1

./scripts/run_eval.sh
```

Useful overrides:

```bash
COMPARE_TASKS=task_a,task_b                 # run a subset
COMPARE_MODEL=gpt-5.4                       # model name passed to the API
COMPARE_REASONING_EFFORT=low                # reasoning effort when supported
COMPARE_GRAPH_ROOT=/path/to/graph-of-skills # same as GRAPH_OF_SKILLS_ROOT
COMPARE_GOSKILLS_ROOT=/path/to/this/repo    # GoSkills checkout
COMPARE_OUTPUT_ROOT=/path/to/generated      # generated task directory
COMPARE_DIRECT_BASE_URL=https://.../v1      # OpenAI-compatible endpoint
```

The runner writes generated datasets, jobs, logs, and metric summaries under `scripts/` by default. These outputs are intentionally ignored by Git.

## ALFWorld Hook

The paper also reports ALFWorld results. This artifact includes a dependency-free selector in `evaluation/alfworld/goskills_selector.py` that an ALFWorld runner can call to obtain the GoSkills captain/support skill plan for a visible goal. Full ALFWorld execution requires the external ALFWorld simulator and assets, which are not bundled in the ZIP.

## Anonymous Submission Notes

For double-blind review:

- do not add author names, affiliations, personal emails, acknowledgments, or institution-specific paths
- do not commit `.env` files, API keys, logs, generated jobs, downloaded datasets, or local caches
- keep external links anonymous and stable if using an anonymous GitHub repository
- freeze the submitted branch or ZIP after the submission deadline
- de-anonymize repository ownership, license metadata, and persistent archival links only after acceptance

The repository is small enough to submit as a ZIP. Large generated datasets and benchmark outputs should be regenerated from the instructions above or linked through an anonymous data URL when allowed by the venue.
