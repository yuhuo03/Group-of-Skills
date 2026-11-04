# Run analysis

Aggregate a campaign produced by `evaluation/experiments/run.py`:

```bash
.venv-eval/bin/python evaluation/analysis/summarize_runs.py runs/gpt54-all \
  --output outputs/gpt54-all
```

The command reads the plan, status, and per-trial receipts and writes `TRIALS.csv`,
`SUMMARY.csv`, and `SUMMARY.json`. It verifies committed receipt hashes and
identities before aggregation. Complete groups report mean reward (percent) and mean input/output tokens
separately. Runtime is mean agent execution time in seconds, excluding
environment setup, verification, and cleanup. Incomplete groups report missing
trials and leave aggregate metrics blank instead of counting missing trials as zeros. No provider or simulator is called.

`scripts/summarize_runs.py` is a shortcut to the same implementation.
