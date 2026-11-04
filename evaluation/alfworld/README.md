# ALFWorld — all five methods

This entrypoint supports `noskills`, `vanilla`, `vector`, `native-gos`, and
`goskills-d`. It uses the recorded GPT-5.4 protocol: ALFWorld 0.4.2 / TextWorld
1.7.0, the out-of-distribution split, seed 42, 30 interaction steps, low reasoning,
and 4,096 maximum completion tokens. Responses must report the recorded model
`gpt-5.4-2026-03-05`; model/usage errors fail the trial instead of becoming zero.

Use the separate Python 3.12 `.venv-retrieval` environment described in the root
README/DATA guide. Its pinned requirements include ALFWorld and the official GoS
checkout. Harbor uses a different environment because its OpenAI SDK dependency
is incompatible with the fixed GoS dependency. Set
`ALFWORLD_DATA` to a licensed, unpacked ALFWorld data directory. Dataset downloads
are a separate setup step; this runner never generates episodes or answers.

## Method inputs and behavior

| Method | Required additional inputs | Skill behavior |
|---|---|---|
| `noskills` | None | No skill adapter |
| `vanilla` | `--skills-root` | Upstream `all_full` metadata catalog and named skill reads |
| `vector` | `--skills-root`, `--workspace` | Official vector-only retrieval; real embeddings |
| `native-gos` | `--skills-root`, `--workspace` | Official graph retrieval; real embeddings |
| `goskills-d` | `--skills-root`, `--pool` | Frozen D group retriever and source-fidelity checks |

All methods require `--upstream` for the original ALFWorld runner, prompts,
`SkillModule`, and token tracker. The checkout must be clean at commit
`203f60a2c689da055ce1ac351eb3cb9912a3bca7`. The current D adapter is the shared
D core used on SkillsBench/TB2, not the obsolete task-name-based ALF selector.

Vector and graph use `text-embedding-3-small`, 1,536 dimensions, top 4 skills,
1,800 characters per skill, 9,000 characters of context, no LLM query rewrite,
and graph seed top-k 5. The upstream ALFWorld query shaping and explicit runtime
skill requests are retained. Each skill request consumes an interaction step.
Vanilla exposes the full metadata catalog; it does not silently become retrieval.

## Plan one task

From the repository root, after obtaining assets (replace the example paths):

```bash
.venv-retrieval/bin/python evaluation/alfworld/run.py \
  --upstream data/external/graph-of-skills \
  --config data/external/graph-of-skills/evaluation/alfworld/base_config.yaml \
  --game-file data/external/alfworld/json_2.1.1/valid_unseen/EXAMPLE/TRIAL/game.tw-pddl \
  --skills-root data/external/skills_2000 \
  --pool data/external/pool.json \
  --workspace data/external/workspace \
  --method goskills-d --output runs/alfworld-goskills-d-new
```

The default only prints a plan and does not import a simulator or API client.
Change `--method` to any of the five IDs. Inputs unused by that method may be
omitted. No Skills does not require a skill library, pool, or index.

To select by the packaged historical game mapping instead, replace `--game-file`
with:

```bash
--game-index 0 --games-manifest configs/alfworld_games.json \
  --data-root data/external/alfworld
```

Relative manifest paths resolve under `--data-root`. On execution, a supplied
manifest game hash must match the file, and the game must belong to the actual
simulator's OOD split. The batch runner in the root README uses explicit game
paths and a fresh subprocess/output directory for each method/task.

## Execute after setup

Set `OPENAI_API_KEY`, and optionally `OPENAI_BASE_URL`, locally. For graph/vector,
the official embedding service uses these same upstream credential/endpoint
variables. The runner pins `GOS_EMBEDDING_MODEL` and `GOS_EMBEDDING_DIM` before
import, and rejects incompatible already-loaded settings. Add `--execute` to the
plan command to run exactly one new episode, including billable model requests.
There is no whole-task retry loop and existing output directories are refused.

The supplied source index is never used as a writable working directory. Each
worker copies it to its own output/index before constructing the official engine.
A missing, failed, non-finite, or wrong-dimension embedding cannot fall back to a
lexical/zero-vector result. These are recorded failures, not valid agent zero scores.

## Outputs and verification

`result.json` contains the original conversation, reward, recorded agent runtime
and token tracker; `api_calls.json` and `transport.json` retain model/usage evidence.
Retrieval/embedding receipts are saved per query. `receipt.json` has normalized
`reward`, `input_tokens`, `output_tokens`, `runtime_seconds`, and source hashes
only after result validation. Environment cleanup failure makes the receipt fail
and exits nonzero. Raw outputs remain private until reviewed for publication.

Tests use injected fake providers/engines and synthetic resources. They exercise
all five plans, graph-versus-vector dispatch, full-library vanilla behavior,
source-index isolation, embedding failure/dimension rejection, and relocation.
They do not call the real API or simulator and do not claim new benchmark scores.
