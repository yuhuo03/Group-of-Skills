# Prepare benchmark inputs

Run these commands from the repository root in the Python 3.12 environment
described in [README](README.md). All destinations are new folders.
External datasets, skill documents and images retain their original licenses.

## 1. Pinned Graph of Skills code and the 2,000-skill library

Create each checkout/environment once. If you already downloaded the skill library
in README Step 1, reuse `data/external/skills_2000` and skip the final download command
below. Its `DOWNLOAD_RECEIPT.json` must record the same `archive_sha256` shown here;
the downloader deliberately refuses to overwrite an existing directory.

```bash
mkdir -p data/external
git clone https://github.com/davidliuk/graph-of-skills.git data/external/graph-of-skills
git -C data/external/graph-of-skills checkout --detach 203f60a2c689da055ce1ac351eb3cb9912a3bca7
uv venv --python 3.12 --seed .venv-retrieval
.venv-retrieval/bin/python -m pip install --upgrade pip setuptools wheel
.venv-retrieval/bin/python -m pip install -r evaluation/requirements/retrieval-alfworld-py312-linux.txt \
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

The task list in `evaluation/configs/task_ids.json` selects 86 SkillsBench tasks.
Use a task checkout containing all selected IDs; the setup check reports any
missing tasks. The preparation step preserves task instructions, tests, resources
and verifier configuration while removing the per-task oracle skill directory.

Download Terminal-Bench 2:

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

This download can be large. `evaluation/configs/alfworld_games.json` maps all 134 selected
OOD IDs to relative game paths and original SHA256 hashes. The doctor and batch
planner check those bytes. Keep the downloaded `logic/` and
`json_2.1.1/valid_unseen/` layout; do not generate substitute episodes.

## 3. Build a directed index and GoSkills group pool

Create one shared index from the library for new experiments. **The `gos index`
command below calls embedding/graph-construction APIs and incurs cost.** It is
separate from local group construction.
Configure `OPENAI_API_KEY` and optional `OPENAI_BASE_URL` in your shell first.
The same route must support chat and `text-embedding-3-small` embeddings.
Replace `YOUR_MODEL_NAME` below with the chat model you choose for graph
construction. If it is already set by your loaded `.env`, skip that export line.

```bash
export GOS_EMBEDDING_MODEL=openai/text-embedding-3-small
export GOS_EMBEDDING_DIM=1536
export GOS_ENABLE_QUERY_REWRITE=false
export GOS_LLM_MODEL=openai/YOUR_MODEL_NAME
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

Preserve the construction report, exported graph and group pool for reuse across
the retrieval methods.

## 4. Local configuration

```bash
cp evaluation/configs/local.example.json evaluation/configs/local.json
.venv-eval/bin/python scripts/doctor.py --config evaluation/configs/local.json --runtime
```

The example matches the directories above, including `retrieval_python` pointing
to `.venv-retrieval/bin/python`. Keep `.venv-eval` active for the batch launcher.
The launcher runs ALFWorld in the retrieval environment and passes its interpreter
to SkillsBench/TB2 retrieval helpers; it does not activate shells or copy credentials. Paths are relative to the JSON file,
not the caller's working directory. Customize them for existing assets. The doctor
is read-only: it reports missing packages/data, commit/game hash mismatches and
credential presence without calling APIs or Docker.

`evaluation/configs/task_ids.json` fixes membership: 86 SkillsBench, 134 ALFWorld and 89 TB2
tasks per method. An optional `tasks` list in each benchmark section selects a
deliberate subset for a new run; summaries retain the planned denominator.
Native task verifiers can download their own dependencies.

## Attribution

GoSkills uses the [Graph of Skills](https://github.com/davidliuk/graph-of-skills)
skill library and benchmark integration as external dependencies. The pinned GoS
checkout retains its MIT license. SkillsBench, Terminal-Bench 2, ALFWorld,
TextWorld, Harbor and the downloaded skill libraries remain under their respective
terms. This repository does not redistribute their datasets, container images
or skill collections.
