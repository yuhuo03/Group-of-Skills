# Benchmark experiments

`run.py` plans or executes the three benchmarks with all five methods. Configure
`configs/local.json` from `configs/local.example.json`; paths are relative to the
configuration file. `configs/task_ids.json` selects the 86 SkillsBench tasks,
134 ALFWorld episodes, and 89 Terminal-Bench 2 tasks. `alfworld_games.json` maps
episode IDs to dataset paths and expected file hashes.

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
