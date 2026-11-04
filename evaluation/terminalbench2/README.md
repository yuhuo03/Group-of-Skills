# Terminal-Bench 2: all five methods

The single-trial entrypoint accepts `noskills`, `vanilla`, `vector`, `native-gos`
and `goskills-d`. Every arm uses the same recorded GPT-5.4 terminal prompt, `low`
reasoning, 4,096 completion-token limit and original task deadline. The five
method differences are:

| Method | Skill access |
|---|---|
| `noskills` | Bash only; no skill library, retrieval or embedding calls |
| `vanilla` | The complete official GoS `all_full` exposure catalog once at startup, with read-only source access; no dynamic retrieval tool |
| `vector` | Official vector retrieval, `text-embedding-3-small`, 1,536 dimensions |
| `native-gos` | Official graph retrieval with the same embedding route, five seeds |
| `goskills-d` | The frozen D group retriever; lexical seeds, no embedding service |

Vector, graph and D expose a `retrieve_skills` tool and an initial retrieval.
Each retrieved context is capped at four skills / 1,800 body characters per skill /
9,000 context characters. The vanilla full catalog intentionally has no top-k
cap. Original skill files are mounted read-only at `/opt/graphskills/skills`.

## Install and prepare inputs

Use two Python 3.12 environments. Harbor 0.20 requires an OpenAI SDK version that
conflicts with pinned GoS's `fast-graphrag` dependency. The Harbor agent therefore
launches official retrieval in the separately selected interpreter. The recorded
TB2 host used Python 3.13.14; the portable dependency snapshots below were resolved
for Python 3.12 on Linux x86_64.

After obtaining the pinned upstream checkout in `data/external/graph-of-skills`
as described in the root DATA guide, run from the release root:

```bash
python3.12 -m venv .venv-eval
.venv-eval/bin/python -m pip install \
  -r requirements/terminal-py312-linux.txt -e '.[terminal]'

python3.12 -m venv .venv-retrieval
.venv-retrieval/bin/python -m pip install \
  -r requirements/retrieval-alfworld-py312-linux.txt \
  -e '.[alfworld]' -e data/external/graph-of-skills
RETRIEVAL_PYTHON="$PWD/.venv-retrieval/bin/python"
```

The second environment is required by `vanilla`, `vector` and `native-gos`, and
can also run ALFWorld. No Skills and D can use the Harbor interpreter alone.
Keep the venv interpreter path itself; do not resolve its symlink to a base Python.
Obtain the raw
TB2 task definitions/images and skill library under their own terms. Vector and
graph require the matching official workspace; D requires a built JSON or exact
compiled group pool. None of those assets is silently downloaded during planning.

Set these paths to your installed assets:

```bash
TASK=/path/to/terminal-bench-2/task-name
SKILLS=/path/to/skills_2000
UPSTREAM=/path/to/graph-of-skills
WORKSPACE=/path/to/matching-gos-workspace
POOL=/path/to/groups.json
```

Plan any of the five methods without API credentials, Docker calls or output
creation; supply only the resources needed for that method:

```bash
.venv-eval/bin/python evaluation/terminalbench2/run.py --task "$TASK" --method noskills --output runs/tb2-none
.venv-eval/bin/python evaluation/terminalbench2/run.py --task "$TASK" --method vanilla \
  --skills-root "$SKILLS" --upstream "$UPSTREAM" --retrieval-python "$RETRIEVAL_PYTHON" --output runs/tb2-vanilla
.venv-eval/bin/python evaluation/terminalbench2/run.py --task "$TASK" --method vector \
  --skills-root "$SKILLS" --upstream "$UPSTREAM" --workspace "$WORKSPACE" \
  --retrieval-python "$RETRIEVAL_PYTHON" --output runs/tb2-vector
.venv-eval/bin/python evaluation/terminalbench2/run.py --task "$TASK" --method native-gos \
  --skills-root "$SKILLS" --upstream "$UPSTREAM" --workspace "$WORKSPACE" \
  --retrieval-python "$RETRIEVAL_PYTHON" --output runs/tb2-graph
.venv-eval/bin/python evaluation/terminalbench2/run.py --task "$TASK" --method goskills-d \
  --skills-root "$SKILLS" --pool "$POOL" --output runs/tb2-d
```

The planning step validates local paths and prints the generated Harbor trial
configuration. It preserves the raw task's CPU, memory, verifier and timeout
multiplier; no global timeout is substituted for task-defined limits. For a
real trial, configure the chat credentials (`OPENAI_API_KEY`, optional
`OPENAI_BASE_URL`) and official embedding credentials for vector/graph, then add
`--execute` to the chosen command. **Execution makes billable API calls and starts
Docker.** Existing output folders are refused; use one fresh folder per trial.

## Outputs and acceptance

The root output contains `trial_config.json` and `receipt.json`; the Harbor trial
subdirectory contains `result.json`, `agent/trajectory.json`, request usage,
retrieval evidence and canonical verifier output. Root `receipt.json` is `VALID`
only after the exact model/usage/transport, retrieval, score, trace and
owned-container cleanup checks pass. It records reward, input/output/cache tokens,
agent runtime seconds and result/trace hashes. Other outcomes are
`PROCESS_FAILED`; missing/null reward or missing canonical tests never becomes0.
A real verified0 remains0, with its recorded costs. There is no score-based retry.

Retrieval occurs in an isolated host subprocess with a 180-second deadline using
`--retrieval-python` (D defaults to the Harbor interpreter). Resource
paths are passed in its structured request rather than shared pool environment
state. Only that owned helper is terminated if its deadline expires. API credentials
are not written into task packs or mounted into benchmark containers.

## Historical environment repairs

The historical campaign used SHA-bound dependency transport and cleanup repairs
for particular images. Those snapshots remain in the companion artifacts. This
entrypoint uses the task's native verifier and does not automatically apply
historical repairs to arbitrary images. Bootstrap failures must be investigated;
they are not legitimate agent zeros. The portable five-arm entrypoints have
synthetic offline coverage; no new paid experiment was run to certify score
replication while preparing this release.
