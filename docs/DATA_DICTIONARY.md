# Data dictionary

`data/selected_trials.csv` is the executable source of the table.

| Field | Meaning |
|---|---|
| id | Unique `benchmark/method/task` ID;1545 unique IDs |
| benchmark | skillsbench / alfworld / tb2 |
| method | Stable normalized method ID |
| task | Benchmark task name or zero-padded ALFWorld index |
| reward | Native task score; SkillsBench may be fractional, ALFWorld/TB2 binary |
| input_tokens | Prompt/input tokens summed for the selected attempt; cached tokens are already included, not added again |
| output_tokens | Completion tokens for the selected attempt; included for inspection, not the Tokens column |
| runtime_seconds | Selected agent execution duration in seconds |
| result_sha256 | SHA256 of original result bytes before redaction |
| selection | selected baseline/candidate/single-r1/retained original/zero-selected repeat replacement |

The JSON version additionally includes source-origin/model-evidence metadata where available. Missing historical fields are not filled with invented values.

For SkillsBench and TB2, runtime derives from `result.agent_execution.finished_at - started_at`. ALFWorld uses its recorded `agent_runtime_seconds`. Neither is total queue + container startup + verifier + cleanup wall-clock time.

`provenance/*traces-manifest.json` contains each source file SHA, release file SHA, byte counts and redaction-category counts. Source SHA identifies the original evidence; it is expected to differ from a redacted release file SHA. `SOURCE_MANIFEST.json` in private raw archives is checked before producing a release archive.

`data/tb2_original445.csv` retains the pre-replacement selected evidence. `data/tb2_selected445.csv` uses the replacement selection. Join by canonical key; never join by trial basename alone.
