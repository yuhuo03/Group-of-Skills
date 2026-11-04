# Prepare benchmark inputs

Run these commands from the extracted repository root in the Python 3.12
environment described in [README](README.md). All destinations are new folders.
The numeric files already in `data/` are recorded results, not benchmark inputs.
External datasets, skill documents and images retain their original licenses.

## 1. Pinned Graph of Skills code and the 2,000-skill library

```bash
mkdir -p data/external
git clone https://github.com/davidliuk/graph-of-skills.git data/external/graph-of-skills
git -C data/external/graph-of-skills checkout --detach 203f60a2c689da055ce1ac351eb3cb9912a3bca7
python3.12 -m venv .venv-retrieval
.venv-retrieval/bin/python -m pip install --upgrade pip setuptools wheel
.venv-retrieval/bin/python -m pip install -r requirements/retrieval-alfworld-py312-linux.txt \
  -e ".[alfworld]" -e data/external/graph-of-skills
.venv-retrieval/bin/python -m pip check

python scripts/fetch_asset.py \
  --url https://huggingface.co/datasets/DLPenn/graph-of-skills-data/resolve/83a8c59f6d09b849e57a50ed2577e253995d257e/skills_2000.tar.gz \
  --sha256 9a616f600488341263f4e931c8387140eb06349a957d498d98a5f5be90109a89 \
  --output data/external/skills_2000 --execute
```

`fetch_asset.py` downloads a public archive, verifies its SHA256, rejects unsafe
archive entries and writes a download receipt. This makes no model requests.
Without `--execute` it only prints a download plan.

Keep the upstream checkout clean. Put data, credentials, outputs and virtual
environments outside it. Vanilla uses its skill exposure implementation; Vector
and Graph of Skills use its distinct retrieval algorithms; ALFWorld uses its
original episode runner and prompts.

## 2. Benchmark data

SkillsBench task definitions come from their upstream repository:

```bash
git clone --filter=blob:none --sparse https://github.com/benchflow-ai/skillsbench.git data/external/skillsbench
git -C data/external/skillsbench sparse-checkout set tasks
git -C data/external/skillsbench rev-parse HEAD > data/external/skillsbench-task-revision.txt
```

The historical SkillsBench task bytes were frozen independently; their originating
upstream commit was not proven. This download records the revision obtained and
is a **new run input**, not a claim of exact historical task bytes. The doctor
checks all 86 selected task IDs. If upstream removed a selected task, use a
licensed archived task snapshot containing those IDs; do not silently reduce the
denominator. Preparation records every task-file hash, removes only the original
per-task oracle skill directory/COPY, and preserves instructions, tests, native
resources and verifier configuration.

Terminal-Bench 2 uses the recorded archive and hash:

```bash
python scripts/fetch_asset.py \
  --url https://codeload.github.com/harbor-framework/terminal-bench-2/tar.gz/69671fbaac6d67a7ef0dfec016cc38a64ef7a77c \
  --sha256 afcd2b9813fc08e8d2b955db8165cc057acf0e37f74e55d26fc2506da196cebe \
  --output data/external/terminal-bench-2 --execute
```

ALFWorld uses the official downloader in the retrieval/ALFWorld environment:

```bash
export ALFWORLD_DATA="$PWD/data/external/alfworld"
.venv-retrieval/bin/alfworld-download
```

This download can be large. `configs/alfworld_games.json` maps all 134 selected
OOD IDs to relative game paths and original SHA256 hashes. The doctor and batch
planner check those bytes. Keep the downloaded `logic/` and
`json_2.1.1/valid_unseen/` layout; do not generate substitute episodes.

## 3. Build a matching directed index and D pool

Create one shared index from the library for new experiments. **The `gos index`
command below calls embedding/graph-construction APIs and incurs cost.** It is
not part of the offline checks and was not executed while packaging this release.
Configure `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` in your shell first.
The same route must support chat and `text-embedding-3-small` embeddings.

```bash
export GOS_EMBEDDING_MODEL=openai/text-embedding-3-small
export GOS_EMBEDDING_DIM=1536
export GOS_ENABLE_QUERY_REWRITE=false
export GOS_LLM_MODEL=openai/gpt-5.4
.venv-retrieval/bin/gos index data/external/skills_2000 --workspace data/external/workspace

export GOSKILLS_OFFICIAL_ROOT="$PWD/data/external/graph-of-skills"
.venv-retrieval/bin/python -m goskills export-native --workspace data/external/workspace \
  --skills-root data/external/skills_2000 --output data/external/native-graph.json
.venv-retrieval/bin/python -m goskills build --graph data/external/native-graph.json \
  --output data/external/pool.json
```

Alternatively, supply a trusted matching workspace with a valid construction
report and its exact skill library, then run only export/build. Do not use the
older undirected `*_v1` downloadable graph as a substitute for this typed directed
index. Export validates graph direction, vector storage, node/source identities,
source bytes and provider-failure evidence. Do not edit receipts to bypass a
failed check. Native index files deserialize upstream data; use trusted inputs.

A newly constructed index can differ from the historical one. Construction cost
is separate from agent token/runtime metrics. Preserve the construction report,
exported graph and pool alongside new results.

## 4. Local configuration

```bash
cp configs/local.example.json configs/local.json
python scripts/doctor.py --config configs/local.json --runtime
```

The example matches the directories above, including `retrieval_python` pointing
to `.venv-retrieval/bin/python`. Keep `.venv-eval` active for the batch launcher.
The launcher runs ALFWorld in the retrieval environment and passes its interpreter
to SkillsBench/TB2 retrieval helpers; it does not activate shells or copy credentials. Paths are relative to the JSON file,
not the caller's working directory. Customize them for existing assets. The doctor
is read-only: it reports missing packages/data, commit/game hash mismatches and
credential presence without calling APIs or Docker.

`configs/task_ids.json` fixes membership: 86 SkillsBench, 134 ALFWorld and 89 TB2
tasks per method. An optional `tasks` list in each benchmark section selects a
deliberate subset for a new run; summaries retain the planned denominator.
Historical package inventories in `configs/*-environment.json` are evidence,
not universal lockfiles. Native task verifiers can still download dependencies.
Historical image-specific repairs remain in the companion source archive.
