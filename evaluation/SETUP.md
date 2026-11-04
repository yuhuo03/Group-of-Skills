# Evaluation setup

Run these commands from the repository root. Full evaluation requires Linux,
Python 3.12, uv, Git, Docker Engine, and Docker Compose v2. Docker must be usable
by your account. TextWorld and hnswlib may also need native build tools; on
Debian/Ubuntu, install `build-essential`, `python3.12-dev`, `libffi-dev`,
`libssl-dev`, `pkg-config`, and `cmake` as needed.

## 1. Install the terminal environment

SkillsBench and Terminal-Bench 2 use Harbor:

```bash
uv venv --python 3.12 --seed .venv-eval
.venv-eval/bin/python -m pip install --upgrade pip setuptools wheel
.venv-eval/bin/python -m pip install \
  -r evaluation/requirements/terminal-py312-linux.txt -e '.[terminal]'
.venv-eval/bin/python -m pip check
```

## 2. Install the retrieval environment

Follow [DATA.md, step 1](../DATA.md#1-pinned-graph-of-skills-code-and-the-2000-skill-library)
to obtain the pinned Graph of Skills checkout and install `.venv-retrieval`
with `evaluation/requirements/retrieval-alfworld-py312-linux.txt`. If already
installed, reuse it.

This environment runs ALFWorld and the upstream skill adapters. Keep the two
environments separate: the terminal requirements pin OpenAI 3.45.0, while the
upstream retrieval requirements pin OpenAI 1.109.1. Reuse environments already
created by this guide. Pass the virtual environment's Python path itself to
runners; resolving its symlink to the system interpreter loses the environment.

## 3. Prepare inputs and configuration

Continue with the benchmark-data and workspace steps in [DATA.md](../DATA.md)
to obtain task datasets and build a GoSkills pool. Copy the local template
once and set its paths to your assets:

```bash
cp evaluation/configs/local.example.json evaluation/configs/local.json
```

Relative paths are resolved from the configuration file's directory.
The template selects `.venv-retrieval/bin/python` for upstream retrieval and
ALFWorld. ALFWorld also needs `ALFWORLD_DATA` pointing to its unpacked dataset.
Benchmark-specific external-service credentials, if required by a task, must
be supplied separately.

## 4. Configure providers

```bash
export OPENAI_API_KEY="YOUR_API_KEY"
# For an OpenAI-compatible endpoint only:
# export OPENAI_BASE_URL=https://YOUR-ENDPOINT/v1
export GOS_EMBEDDING_MODEL=openai/text-embedding-3-small
export GOS_EMBEDDING_DIM=1536
```

The launchers read these shell variables; they do not automatically load
`.env`. Vector Skills and Graph of Skills need the same embedding model and
dimension as their workspace. GoSkills uses lexical retrieval and needs no
embedding service.

## 5. Check local setup

```bash
.venv-eval/bin/python scripts/doctor.py \
  --config evaluation/configs/local.json --runtime
```

This checks installed dependencies and local inputs without API requests or
Docker commands. It does not test provider access or run a simulator.

Continue with the [batch runner](README.md), or the single-trial guides for
[SkillsBench](skillsbench/README.md), [ALFWorld](alfworld/README.md), and
[Terminal-Bench 2](terminalbench2/README.md). Commands print a plan by default;
`--execute` starts a new trial.
