# Benchmark experiments

`run.py` plans or executes the three benchmarks with all five methods. Configure
`configs/local.json` from `configs/local.example.json`; paths are relative to the
configuration file. `configs/task_ids.json` defines the selected tasks for all
three benchmarks. `alfworld_games.json` maps episode IDs to dataset paths and expected file hashes.

From the repository root, after [setup](../README.md#setup):

```bash
.venv-eval/bin/python evaluation/experiments/run.py \
  --config evaluation/experiments/configs/local.json \
  --benchmark all --methods all --output runs/gpt54-all
```

This prints a plan. Add `--execute` to run it with APIs and benchmark environments.
The batch runner uses the configured retrieval interpreter for ALFWorld and a
separate process per task. Use a fresh output directory; completed results are
preserved, and an invalid trial stops further dispatch. See the
[benchmark guides](../README.md) for single-trial commands.

Use `--workers N --per-method M` for bounded parallel execution. To continue an
interrupted campaign, use `--resume --output PATH` and then add `--execute` after
reviewing the plan. Resume preserves completed attempts, including valid zeros;
it dispatches only previously unclaimed jobs. See [resume details](../README.md#resume-a-campaign).

For TB2, optionally set `tb2.verifier_assets` to a relative path to the four-root
asset configuration described in the [TB2 guide](../terminalbench2/README.md#verifier-environment-support).
Planning checks all catalogue-listed assets before any job is dispatched; resume
refuses changes to those inputs.

## Library-size experiments

Published 200/500/1,000/2,000-skill libraries and matching workspaces are available
on [Hugging Face](https://huggingface.co/datasets/yuhuo03/group-of-skills-data).
Use [the download script](../../DATA.md#1-skill-libraries-and-prebuilt-workspaces)
for these inputs. The following subset workflow is optional for custom libraries.

The preparation follows the GoS skillset pattern: retain an explicit set of base
skills and fill larger sets in lexicographic order. All subsets share the same
source library and preserve complete skill directories, including helpers and
license files. This produces **new experimental inputs**; it does not assert the
membership of historical paper experiments.

```bash
python -m goskills_eval.experiments.skillsets \
  --skills-root data/external/skills_2000 \
  --sizes 200,500,1000,2000 --output data/scale-libraries
```

This prints a plan. Add `--execute` to copy local files. To retain a specific base
set, supply `--required-members path/to/members.json`, a JSON list of skill
directory names. Without it, the subsets use sorted source names. Sizes such as
100 are supported when the source library and required membership permit them;
they are not presented as existing paper assets. Selection never reads task
answers or oracle skills. Existing outputs are not overwritten.

For **each** library, follow [DATA.md Step 3](../../DATA.md#3-build-a-directed-index-and-goskills-group-pool)
to build its own directed workspace, export, identity binding and pool. Index
construction calls the configured APIs; copying libraries and building groups
are local. Do not reuse a 2,000-skill index with a 200-skill library or relabel an
old undirected index as a rebuilt directed one.

Create one normal evaluation configuration per size. Keep model, task inputs,
task list, upstream checkout and interpreters fixed; change only `skills_root`,
`workspace` and `pool`. Then write a manifest such as:

```json
{
  "schema_version": 1,
  "membership": "nested",
  "libraries": [
    {"size": 200, "config": "scale-200.json"},
    {"size": 500, "config": "scale-500.json"},
    {"size": 1000, "config": "scale-1000.json"},
    {"size": 2000, "config": "scale-2000.json"}
  ]
}
```

Configuration paths are relative to the manifest. If using independently
constructed libraries, declare `"membership": "independent"`; nested libraries
must preserve every smaller member and its auxiliary files byte for byte.

```bash
.venv-eval/bin/python -m goskills_eval.experiments.scale \
  --manifest data/scales.json --benchmark skillsbench --methods all \
  --workers 4 --per-method 2 --output runs/scale-study --prepare
```

Without `--prepare`, this is a read-only preflight. With it, the command saves
checked campaign plans and prints the execution commands. Neither mode calls
APIs or Docker. Execute one prepared campaign using the printed command:

```bash
.venv-eval/bin/python -m goskills_eval.experiments.run \
  --resume --output runs/scale-study/skills-200 --execute
```

Run each campaign once and summarize each size separately with
`evaluation/analysis/summarize_runs.py`. All five methods are supported. No Skills
does not consume a library but is a separate trial at each selected size; omit it
with an explicit method list if your protocol uses one shared baseline. Planning
rejects different models or task bytes between sizes, even if task IDs match.

## Component experiments

Build fresh pools from the **same** graph and library:

```bash
python -m goskills_eval.experiments.prepare_ablations \
  --graph data/external/native-graph.json \
  --skills-root data/external/skills_2000 \
  --output data/component-pools --execute
```

Without `--execute`, the command only checks inputs and prints definitions.
Pool construction is local and makes no model calls. The full pool equals the
normal production build. Other pools record their exact transformation and
source identity; the input graph and existing pools are preserved.

| Condition | Change |
|---|---|
| `full` | Unchanged production policy |
| `singleton-groups` | Build groups of one skill; retain atomic compatibility |
| `single-group-plan` | Select at most one group; retain its members and backfill |
| `no-coverage-backfill` | Disable backfill while keeping debt accounting |
| `no-group-graph` | Remove lifted group edges and adjacency; retain within-group topology |

All conditions retain four presented skills, 1,800 characters per skill and
9,000 total context characters as upper bounds. To evaluate a condition, copy
your normal configuration, set `pool` to that condition's JSON, and use the
existing `run.py --methods goskills-d` entrypoint with a fresh output directory.
Keep all other settings and task membership fixed. JSON pools can also be
[compiled](../../DATA.md#3-build-a-directed-index-and-goskills-group-pool).

These are defined experiments for the released implementation, not a claim to
reproduce every historical paper ablation. In particular, anchor selection,
role-label rendering and the contract-only controls need their original precise
definitions before they can be mapped to paper rows. Setting one anchor weight
to zero would not disable the retriever's separate specificity preference, so
that shortcut is not labeled “without anchor selection.” No historical scores
or results are generated by these scripts.
