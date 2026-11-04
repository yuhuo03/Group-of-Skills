# SkillsBench

This runner prepares a method-specific task pack from a raw SkillsBench task and
executes it with Harbor. It uses the SkillsBench bash-only agent and prompt,
GPT-5.4 with low reasoning, 60 turns, a 4,096-token completion limit per call,
a 180-second tool timeout, and a 900-second agent limit.

## Setup and inputs

Complete [environment setup](../README.md#setup) and [input preparation](../../DATA.md).
Run the entrypoint with `.venv-eval/bin/python`. Vector and Graph of Skills also
use `.venv-retrieval/bin/python` for upstream retrieval.

Supply a raw task directory containing `instruction.md`, `task.toml`,
`environment/Dockerfile`, and its verifier files. Docker Engine and Compose v2
are required for execution. Skill methods require the clean Graph of Skills
checkout at commit `203f60a2c689da055ce1ac351eb3cb9912a3bca7` for their method
guides.

| Method | Additional inputs | Skill access |
|---|---|---|
| `noskills` | None | No skills |
| `vanilla` | Skills root, upstream | Full library on the filesystem |
| `vector` | Skills root, workspace, upstream, retrieval Python | Upstream vector retrieval |
| `native-gos` | Skills root, workspace, upstream, retrieval Python | Upstream graph retrieval |
| `goskills-d` | Skills root, pool, upstream | GoSkills group retrieval |

Vector and Graph of Skills require a matching `text-embedding-3-small` workspace
with 1,536-dimensional vectors. Retrieval presents at most four skills,
1,800 characters per skill, and 9,000 context characters. Query rewriting is
disabled; Graph of Skills uses five seeds and GoSkills uses four lexical seeds.

## Plan, prepare, and execute

From the repository root:

```bash
TASK=data/external/skillsbench/tasks/TASK
SKILLS=data/external/skills_2000
UPSTREAM=data/external/graph-of-skills
WORKSPACE=data/external/workspace
POOL=data/external/pool.json
RETRIEVAL_PYTHON="$PWD/.venv-retrieval/bin/python"

.venv-eval/bin/python evaluation/skillsbench/goskills_benchmark.py \
  --method goskills-d --task "$TASK" --skills-root "$SKILLS" \
  --pool "$POOL" --upstream "$UPSTREAM" --output runs/sb-goskills-TASK

.venv-eval/bin/python evaluation/skillsbench/goskills_benchmark.py \
  --method noskills --task "$TASK" --output runs/sb-noskills-TASK

.venv-eval/bin/python evaluation/skillsbench/goskills_benchmark.py \
  --method vanilla --task "$TASK" --skills-root "$SKILLS" \
  --upstream "$UPSTREAM" --output runs/sb-vanilla-TASK

.venv-eval/bin/python evaluation/skillsbench/goskills_benchmark.py \
  --method vector --task "$TASK" --skills-root "$SKILLS" \
  --workspace "$WORKSPACE" --upstream "$UPSTREAM" \
  --retrieval-python "$RETRIEVAL_PYTHON" --output runs/sb-vector-TASK

.venv-eval/bin/python evaluation/skillsbench/goskills_benchmark.py \
  --method native-gos --task "$TASK" --skills-root "$SKILLS" \
  --workspace "$WORKSPACE" --upstream "$UPSTREAM" \
  --retrieval-python "$RETRIEVAL_PYTHON" --output runs/sb-graph-TASK
```

The default validates inputs and prints a plan without creating outputs or
calling Docker or APIs. Use a fresh `--output` directory for each trial.
Append `--prepare-only` to
write a local task pack, method guide, and trial configuration for inspection.
To run a trial, use a new output path and append `--execute` to the raw-task
command. Provider variables are described in [provider setup](../README.md#4-configure-providers).
Execution starts Docker and makes model API requests.

## Task preparation

The runner removes the task's oracle skill directory and its matching Docker
copy directive. It preserves the original instruction, task configuration, and
verifier files, including CPU, memory, network, and scoring settings.
Ambiguous Docker copy directives, task symlinks, external Compose dependencies,
and unsupported non-Linux tasks require explicit preparation before use.

The method guide is available at `/root/AGENTS.md`. Vanilla mounts the library
at `/opt/skillsbench/skills`; retrieval methods use `/opt/graphskills/skills`.
Standalone `vectorskills-query`, `graphskills-query`, and `goskills-query`
commands run through the host retrieval bridge. Use them as standalone commands:
shell chains, pipes, redirects, and environment prefixes are not supported.
Provider credentials remain on the host.

## Outputs

Each run includes the prepared task, `trial_config.json`, `receipt.json`,
Harbor result and verifier files, trajectory, API usage, and retrieval records.
A valid receipt requires a confirmed model, finite reward, canonical test report,
and completed cleanup. Fractional rewards and valid zeros are preserved;
missing reports, null rewards, and environment or transport errors remain failed
trials.

Token counts come from model responses. Runtime measures agent execution and
excludes environment setup, verification, and cleanup. Use the
[batch runner and summarizer](../README.md) for task-level and method-level tables.
