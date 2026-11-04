# ALFWorld

The runner supports all five methods with ALFWorld 0.4.2 and TextWorld 1.7.0.
It uses the out-of-distribution split, seed 42, GPT-5.4 with low reasoning,
30 interaction steps, and a 4,096-token completion limit.

The defaults use the shared `gpt54` reproduction profile. For another model,
use the [shared model options](../README.md#model-profiles).

## Setup and inputs

Complete [environment setup](../README.md#setup) and [input preparation](../../DATA.md).
Run ALFWorld with `.venv-retrieval/bin/python` and set `ALFWORLD_DATA` to the
unpacked ALFWorld dataset.

Every method requires the clean Graph of Skills checkout at commit
`203f60a2c689da055ce1ac351eb3cb9912a3bca7` for the ALFWorld runner, prompts,
and skill interface, plus its `base_config.yaml` and an OOD game file.

| Method | Additional inputs | Skill access |
|---|---|---|
| `noskills` | None | No skills |
| `vanilla` | Skills root | Full metadata catalog and named skill reads |
| `vector` | Skills root, workspace | Upstream vector retrieval |
| `native-gos` | Skills root, workspace | Upstream graph retrieval |
| `goskills-d` | Skills root, pool | GoSkills group retrieval |

Vector and Graph of Skills use `text-embedding-3-small` with 1,536 dimensions,
at most four skills, 1,800 characters per skill, and 9,000 context characters.
Graph retrieval uses five seeds; query rewriting is disabled. Each explicit
skill request consumes an interaction step.

## Plan and execute

From the repository root, replace the example game path:

```bash
.venv-retrieval/bin/python evaluation/alfworld_run.py \
  --upstream data/external/graph-of-skills \
  --config data/external/graph-of-skills/evaluation/alfworld/base_config.yaml \
  --game-file data/external/alfworld/json_2.1.1/valid_unseen/EXAMPLE/TRIAL/game.tw-pddl \
  --skills-root data/external/skills_2000 \
  --pool data/external/pool.json \
  --workspace data/external/workspace \
  --method goskills-d --output runs/alfworld-goskills-new
```

Change `--method` to any identifier in the table. Inputs unused by that method
may be omitted. The default prints a plan without importing the simulator or
calling an API. Add `--execute` to run one episode using the provider variables
in [provider setup](../README.md#4-configure-providers). Use a fresh output directory.

To select a task by the supplied game mapping, replace `--game-file` with:

```bash
--game-index 0 --games-manifest evaluation/experiments/configs/alfworld_games.json \
  --data-root data/external/alfworld
```

Manifest paths resolve under `--data-root`. The runner checks the game hash and
OOD membership before execution. Use the [batch runner](../README.md) for
multiple tasks or methods.

## Outputs

Each run writes `result.json` with the conversation and reward, API usage and
transport records, retrieval records, and a normalized `receipt.json`.
The receipt contains reward, input/output tokens, and agent runtime only after
result validation. Missing scores, model/usage errors, embedding failures, or
cleanup failures produce an invalid trial rather than a zero score. The runner
does not retry episodes automatically.

Upstream workspaces are copied into the run directory before retrieval so the
source index remains unchanged.
