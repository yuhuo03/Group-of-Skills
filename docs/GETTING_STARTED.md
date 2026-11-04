# Full evaluation setup


Use **Linux, Python 3.12, Git, Docker Engine and Docker Compose v2** for the full
stack. Docker must be usable by your account. Native build tools may be required
by TextWorld and hnswlib; on Debian/Ubuntu install `build-essential`,
`python3.12-dev`, `libffi-dev`, `libssl-dev`, `pkg-config`, and `cmake` if needed.
Core-only use remains Python 3.10+. For a fresh evaluation environment:

```bash
python3.12 -m venv .venv-eval
. .venv-eval/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements/terminal-py312-linux.txt -e ".[terminal]"
```

The release uses two Python environments: `.venv-eval` for Harbor/SB/TB2 and
`.venv-retrieval` for the pinned GoS retrievers and ALFWorld. Harbor's dependency
requires OpenAI SDK2, while the fixed GoS dependency requires SDK1. Do not install
both stacks in the same environment. The checked Linux/Python3.12 requirement
files keep them separate; the batch configuration selects the right interpreter.

Follow [DATA.md](../DATA.md) in order: obtain the pinned upstream code, skill
library and task datasets; build or supply a compatible directed index and D
pool; copy `configs/local.example.json` to `configs/local.json`. That guide gives
all commands and input hashes where known. Index construction can incur its own
API cost; offline table reproduction needs none of these large assets.

Provide `OPENAI_API_KEY` in your shell and optionally `OPENAI_BASE_URL` for a
compatible endpoint. Do not put keys in JSON configs. Vector/Graph use the same
route for `text-embedding-3-small` at 1,536 dimensions. `.env.example` documents
variables, but launchers do not source `.env` automatically. Then run:

```bash
python scripts/doctor.py --config configs/local.json --runtime
```

This checks local dependencies and inputs without API requests or Docker
commands. A passed doctor is a setup check, not a paid endpoint/simulator test.

## Plan, execute, summarize

From the repository root, the default command only prints a plan:

```bash
python scripts/run_benchmark.py --config configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all
```

To actually run all 15 combinations after setup, explicitly add `--execute`:

```bash
python scripts/run_benchmark.py --config configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all --execute
python scripts/summarize_runs.py runs/gpt54-all --output outputs/gpt54-all-table
```

The execution command makes billable model/embedding requests and runs benchmark
environments. It is shown for downstream users; it was **not executed** while
preparing this release. The batch launcher is sequential, uses one fresh process
per trial, and does not retry scores. Use a new output directory each time.

To run one benchmark, one method, or a small task subset:

```bash
python scripts/run_benchmark.py --config configs/local.json \
  --benchmark tb2 --methods goskills-d --tasks adaptive-rejection-sampler \
  --output runs/tb2-one
# Add --execute only when ready. --tasks applies to one benchmark at a time.
```

`PLAN.json` fixes intended membership; `STATUS.json` records completed jobs and
receipt hashes. Each trial preserves its trajectory, token usage, retrieval
records and score evidence. A valid zero remains zero. An environment, transport
or incomplete-verifier failure stops dispatch; remaining jobs stay unexecuted.
There is no automatic resume/retry that could duplicate completed work.

The summarizer writes `TRIALS.csv`, `SUMMARY.csv` and `SUMMARY.json`, including
reward/success percentage, mean input/output tokens and mean agent runtime.
It verifies receipt identities/hashes and supports moving the whole run folder.
Incomplete groups keep their missing count and have no complete-group score;
missing results are never counted as zero. Generated traces may contain task
content and model outputs; review them before publishing.

The release separates the frozen retrieval method from newly portable evaluation
wiring. Source commitments are under `provenance/`. Historical server recovery
controllers are retained in the companion artifacts, not invoked by these
entrypoints. Offline validation does not establish exact new benchmark scores.


See the [benchmark guides](../evaluation/README.md) for single-trial commands.
