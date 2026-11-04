# Three benchmarks, five methods

| Benchmark | No Skills | Vanilla | Vector | Graph of Skills | GoSkills D | Entry |
|---|---|---|---|---|---|---|
| SkillsBench | supported | supported | supported | supported | supported | [raw task runner](skillsbench/README.md) |
| ALFWorld | supported | supported | supported | supported | supported | [episode runner](alfworld/README.md) |
| Terminal-Bench 2 | supported | supported | supported | supported | supported | [task runner](terminalbench2/README.md) |

Method IDs are `noskills`, `vanilla`, `vector`, `native-gos`, `goskills-d`.
Each benchmark keeps its own prompt and skill-access protocol. Vector and Graph
use the real pinned upstream engines and checked 1,536-dimensional embeddings;
GoSkills D uses the frozen group-retrieval core. They are distinct methods.
SkillsBench builds a fresh method pack directly from a raw task.

Start with [installation and batch commands](../README.md) and
[asset preparation](../DATA.md). Single-trial and batch entrypoints default to
planning. Explicit `--execute` creates fresh outputs and makes paid requests.
The batch runner launches one independent process per trial and stops on an
invalid trial. A valid zero is recorded normally; it is not retried.

Outputs include normalized receipts, traces, retrieval evidence and verifier
results. `scripts/summarize_runs.py` produces trial and method tables. A
missing/null/environment-failed result is never substituted with zero.

See [protocol and portability](../docs/EVALUATION.md). These are newly portable
evaluation entrypoints, not copies of the historical multi-server controllers.
Offline tests cover all 15 combinations; no live benchmark replication was run
while packaging this version.
