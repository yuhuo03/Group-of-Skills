# SkillsBench: five methods from raw tasks

The entrypoint prepares a fresh method task pack from a raw SkillsBench task,
then optionally executes one Harbor trial. It does not require historical run
folders or task packs. It retains the SkillsBench bash-only agent, its original
prompt prefix, GPT-5.4/low, 60 turns, 4096 maximum completion tokens per call,
180-second tool timeout and 900-second agent limit. It does not use the TB2
system prompt.

## Install and obtain inputs

From this repository's root, install the terminal extra in a compatible Python
runtime and follow the root README's pinned upstream/assets instructions. Keep
the Harbor environment separate from the GoS retrieval environment:

```bash
# Run in the Harbor virtual environment.
python -m pip install -e '.[terminal]'
```

Harbor 0.20 requires a newer OpenAI SDK through LiteLLM, while the pinned GoS
stack requires OpenAI SDK 1.x. Do not install the two dependency sets in one
virtual environment. Install the release and pinned GoS dependencies in a second
Python environment following the root README, then pass its executable as
`--retrieval-python /path/to/gos-venv/bin/python` for Vector and Graph of Skills.
The entrypoint itself runs with Harbor Python. The exact venv executable path is
preserved; resolving its symlink to the base Python would lose the venv.

Docker Engine/Compose must be available for execution. Supply the raw benchmark
task directory containing `instruction.md`, `task.toml`, `environment/Dockerfile`
and the original verifier files. The benchmark tasks and skill library are
external licensed inputs; paths in examples are placeholders for your copies.

Use the pinned Graph of Skills checkout specified in the root README for
`--upstream`. Its original method `AGENTS.md` templates are used for the skill
conditions. Before preparation or execution, every skill method checks the local
checkout commit and rejects tracked modifications; this check makes no API calls. Vector and Graph of Skills additionally need a prebuilt workspace
for **text-embedding-3-small, 1536 dimensions** and the upstream GoS dependencies.
GoSkills needs a group pool built by the release's `goskills build` command.
Follow the root README to build these inputs; no experiment can infer a valid
index from an empty directory or use a sample pool as the full benchmark library.

| Method flag | SkillsBench condition | Required inputs beyond the task |
|---|---|---|
| `noskills` | No external skill library | none |
| `vanilla` | Full library on the filesystem, read on demand | skills root, upstream |
| `vector` | Official embedding-only retrieval | skills root, workspace, upstream, retrieval Python |
| `native-gos` | Official native graph retrieval, hybrid seed 5 | skills root, workspace, upstream, retrieval Python |
| `goskills-d` | Release D bounded group contract | skills root, pool, upstream |

Vector/Graph retrieve at most four skills, at most 1800 characters per skill and
9000 context characters; query rewriting is disabled. Their embedding failures
are fatal and cannot silently fall back to lexical D retrieval. D uses its
recorded lexical seed-4 policy. SkillsBench Vanilla retains its original
filesystem semantics; it does not receive the ALFWorld/TB2 catalog prompt.

## Plan, prepare, execute

Every command defaults to a local plan. It prints configuration without creating
an output directory, importing a model client, starting Docker or calling APIs.
Use a fresh `--output` directory for each run.

```bash
python evaluation/skillsbench/run.py --method noskills \
  --task /data/skillsbench/tasks/TASK --output runs/sb-noskills-TASK

python evaluation/skillsbench/run.py --method vanilla \
  --task /data/skillsbench/tasks/TASK --skills-root /data/skills \
  --upstream /data/graph-of-skills --output runs/sb-vanilla-TASK

python evaluation/skillsbench/run.py --method vector \
  --task /data/skillsbench/tasks/TASK --skills-root /data/skills \
  --workspace /data/gos-index --upstream /data/graph-of-skills \
  --retrieval-python /path/to/gos-venv/bin/python \
  --output runs/sb-vector-TASK

python evaluation/skillsbench/run.py --method native-gos \
  --task /data/skillsbench/tasks/TASK --skills-root /data/skills \
  --workspace /data/gos-index --upstream /data/graph-of-skills \
  --retrieval-python /path/to/gos-venv/bin/python \
  --output runs/sb-native-gos-TASK

python evaluation/skillsbench/run.py --method goskills-d \
  --task /data/skillsbench/tasks/TASK --skills-root /data/skills \
  --pool /data/groups.json --upstream /data/graph-of-skills \
  --output runs/sb-goskills-d-TASK
```

Append `--prepare-only` to write the copied task, method guide, prompt,
`PREPARATION.json` and `trial_config.json` without Docker or model calls. That
output is an inspection artifact; to execute afterward, use a fresh output and
append `--execute` to the original raw-task command. Existing outputs are never
overwritten or resumed automatically.

For actual execution, provide `OPENAI_API_KEY` and optionally `OPENAI_BASE_URL`
in the host environment. Configure the official upstream embedding provider on
the host as described in the root README. Append `--execute` only when you
intend a billable new trial. Benchmark-specific external-service credentials,
when declared by the original task, remain a separate prerequisite. The release
does not invent or embed them. A legacy `--config` supports validation only;
execute the fresh `--task` entrypoint to obtain the complete evidence contract.

For repeated task/method combinations, use the root batch runner. Each trial
runs in a separate Python worker, owns its output directory and retains its own
receipt. No failed or zero-score result is retried automatically.

## Task isolation and portable retrieval

All methods remove the task's oracle `environment/skills` directory and its
unambiguous, single-source Docker `COPY skills ...` directive, matching the
original baseline isolation convention. Removed files are listed in the
preparation manifest. Ambiguous JSON/multi-source `COPY`/`ADD`, task symlinks and
previously prepared method packs are rejected for explicit preparation.

The original `instruction.md`, `task.toml` and all verifier files are checked
byte-for-byte after copying. CPU, memory, task network policy, verifier timeout
and scoring are not overridden. An existing `environment/docker-compose.yaml`
is preserved with all its services; Harbor 0.20 adds the method's read-only
library mount after the task compose file. External compose `include`/`extends`
and build contexts outside the task are rejected because they cannot be copied
portably. A single alternate compose filename is renamed to `docker-compose.yaml` with
its bytes preserved and the source name recorded; multiple compose files require
an explicit merged task. Image-only/Windows tasks need explicit conversion to a
supported raw Linux task, rather than being silently run with different settings.

The agent reads the method guide at `/root/AGENTS.md`. Vanilla mounts the library
at `/opt/skillsbench/skills`; the three retrieval methods use
`/opt/graphskills/skills`. Ordinary bash executes inside the task container.
Standalone `vectorskills-query`, `graphskills-query` or `goskills-query` calls
are intercepted by the bash adapter and dispatched to an owned host process.
Vector/Graph use the explicitly supplied retrieval interpreter. GoSkills D can
use Harbor Python by default because its lexical retrieval needs no upstream
OpenAI SDK; an explicit retrieval interpreter is also accepted. Vanilla makes
no retrieval subprocess calls.
Query text is passed as JSON data, never evaluated by a host shell. Chained
commands, environment prefixes, pipes, redirects and unsupported flags are
rejected with an explanation. The same source paths are available read-only in
the container. API provider settings remain on the host.

This host retrieval bridge is **new portable transport code**, not a claim that
the historical image/bootstrap bytes or recovery controllers were replayed.
The original method guidance and distinct SkillsBench agent loop are retained;
the guide explains the standalone-command transport change. Historical image
repairs, verifier caches, download mirrors and special credential-route adapters
are not enabled globally. New environment/dependency failures remain failures.

## Results and validity

A run contains `receipt.json`, prepared input hashes, the trial configuration,
Harbor result/verifier outputs, model-call usage, trajectory and retrieval
receipts. A successful process exit alone is insufficient: the root receipt is
`VALID` only when the actual model, transport, method retrieval evidence,
canonical nonempty CTRF report, finite reward in `[0,1]` and exact owned-container
cleanup all pass. Fractional SkillsBench rewards are retained. Missing reports,
null rewards, unconfirmed cleanup and transport failures become `PROCESS_FAILED`,
not score zero.

`input_tokens`, `output_tokens` and available `cached_tokens` come from recorded
model responses. `runtime_seconds` is the recorded agent-execution duration,
excluding environment setup, verifier and cleanup; absent metrics are rejected
instead of filled with zeros. `result_sha256` and `trace_sha256` bind the receipt
to its underlying files. Runtime and retrieval evidence must not be confused
with reproduced historical scores.

Offline tests use fake Harbor/provider fixtures and exercise all five plans,
input preservation, strict query dispatch and result acceptance. No actual
Docker or API experiment was run while building this release.
