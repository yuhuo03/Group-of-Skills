# Terminal-Bench 2

The runner supports all five methods with the GPT-5.4 terminal prompt, low
reasoning, a 4,096-token completion limit, and each task's original deadline.

The defaults use the shared `gpt54` reproduction profile. For another model,
use the [shared model options](../README.md#model-profiles).

## Setup and inputs

Complete [environment setup](../README.md#setup) and [input preparation](../../DATA.md).
Run the entrypoint with `.venv-eval/bin/python`. Vanilla, Vector, and Graph of
Skills also use the separate `.venv-retrieval/bin/python` environment.
GoSkills and No Skills can use the terminal environment alone.

Supply raw Terminal-Bench 2 task definitions and their images. Task CPU, memory,
verifier settings, and timeout multipliers are retained.

| Method | Additional inputs | Skill access |
|---|---|---|
| `noskills` | None | Bash only |
| `vanilla` | Skills root, upstream, retrieval Python | Full metadata catalog and read-only source access |
| `vector` | Skills root, workspace, upstream, retrieval Python | Upstream vector retrieval |
| `native-gos` | Skills root, workspace, upstream, retrieval Python | Upstream graph retrieval |
| `goskills-d` | Skills root, pool | GoSkills group retrieval |

Vector and Graph of Skills use `text-embedding-3-small` with 1,536 dimensions;
Graph of Skills uses five seeds. GoSkills uses lexical seeds. These three methods
receive initial retrieval and a `retrieve_skills` tool, with at most four skills,
1,800 characters per skill, and 9,000 context characters. Vanilla receives the
full catalog without a top-k cap. Source files are mounted read-only at
`/opt/graphskills/skills`.

## Plan and execute

From the repository root, set paths to your installed assets:

```bash
TASK=data/external/terminal-bench-2/TASK
SKILLS=data/external/skills_2000
UPSTREAM=data/external/graph-of-skills
WORKSPACE=data/external/workspace
POOL=data/external/pool.json
RETRIEVAL_PYTHON="$PWD/.venv-retrieval/bin/python"

.venv-eval/bin/python evaluation/terminalbench2/terminalbench2_benchmark.py \
  --task "$TASK" --method noskills --output runs/tb2-noskills

.venv-eval/bin/python evaluation/terminalbench2/terminalbench2_benchmark.py \
  --task "$TASK" --method vanilla --skills-root "$SKILLS" \
  --upstream "$UPSTREAM" --retrieval-python "$RETRIEVAL_PYTHON" \
  --output runs/tb2-vanilla

.venv-eval/bin/python evaluation/terminalbench2/terminalbench2_benchmark.py \
  --task "$TASK" --method vector --skills-root "$SKILLS" \
  --upstream "$UPSTREAM" --workspace "$WORKSPACE" \
  --retrieval-python "$RETRIEVAL_PYTHON" --output runs/tb2-vector

.venv-eval/bin/python evaluation/terminalbench2/terminalbench2_benchmark.py \
  --task "$TASK" --method native-gos --skills-root "$SKILLS" \
  --upstream "$UPSTREAM" --workspace "$WORKSPACE" \
  --retrieval-python "$RETRIEVAL_PYTHON" --output runs/tb2-graph

.venv-eval/bin/python evaluation/terminalbench2/terminalbench2_benchmark.py \
  --task "$TASK" --method goskills-d --skills-root "$SKILLS" \
  --pool "$POOL" --output runs/tb2-goskills
```

Commands validate local inputs and print the trial configuration by default.
After configuring providers in [provider setup](../README.md#4-configure-providers), add `--execute` to run
one trial. Execution starts Docker and makes API requests. Use a new output
directory for every single trial. The batch runner supports explicit resume of
never-dispatched jobs and never retries completed attempts based on their score.

For multiple tasks or methods, use the [batch runner](../README.md).

## Outputs

The output contains `trial_config.json` and `receipt.json`. The Harbor trial
directory contains `result.json`, `agent/trajectory.json`, request usage,
retrieval records, and verifier outputs. A valid receipt requires confirmed
model/usage records, method retrieval evidence, a finite reward and canonical
test report, a trajectory, and completed cleanup.

After a trial exits, even when result assessment fails, the runner checks its exact
Compose project. If Harbor left one main container, the cleanup hook waits for
two observations of the stopped state, then rechecks the full ID, project,
service and state immediately before a non-force removal. Running containers,
unexpected identities, multiple residual containers and failed Docker queries
remain unresolved. It never kills containers, removes volumes or restarts the
daemon. `cleanup_observation.jsonl` and `cleanup_receipt.json` record the outcome;
a final empty-project check is required before the trial becomes valid.

Receipts record reward, input/output/cache tokens, agent runtime in seconds,
and result/trace hashes. Missing or null results and environment failures remain
failed trials; a verified zero remains zero. Agent runtime excludes environment
setup, verification, and cleanup.

Retrieval uses an isolated host process with a 180-second deadline. Keep the
virtual environment executable path in `--retrieval-python`; provider
credentials are not written into task packs or mounted into task containers.

## Verifier environment support

The default runner currently uses Harbor's task verifier plus the strict cleanup
hook above. The historical server also used dependency-cache, image-identity and
public-asset-mode adapters. That complete adapter chain has not yet been ported
and validated here on Linux/Harbor, so the release is not a byte-identical
reproduction of that server's verifier environment.

`goskills_eval.terminalbench2.uv_transport` supplies a separately tested,
exact-script wrapper for verified official uv 0.9.5 binaries. It is not enabled
by the default runner. This local component does not establish that the complete
historical environment fixes are active or that every task's installer will
succeed on a new machine.
