# Evaluation protocol and portability boundary

## What this code contains

- The exact optimized D core used in GPT-5.4 SkillsBench, ALFWorld and TB2.
- A lossless read-only SQLite pool reader and a normal JSON pool reader.
- Source-fidelity validation for every presented skill's name, source spans,
  truncation disclosure, group membership, pool hash and configuration.
- All five recorded methods on each benchmark. ALFWorld retains its original
  skill-request protocol; TB2 retains its retrieval tool; SkillsBench gets a
  fresh raw-task pack and host-side standalone query bridge.
- The actual shared Harbor direct-API base and cancellable transport, with only
  relative imports adapted. The TB2 subclass preserves its distinct terminal
  prompt, remaining-task command deadline and explicit retrieval tool.
- New one-trial wrappers/config builders that require user-supplied benchmark
  assets. These wrappers are **new release code**, not the bytes that launched
  the historical campaigns. Their provenance is separate from original results.

`provenance/EVALUATION_SOURCE.json` records source/release SHA and modifications.

## Recorded model protocol

| Track | Scope per method | Model | Reasoning | Agent limit |
|---|---:|---|---|---|
| SkillsBench |86 tasks|GPT-5.4|low|900 seconds;60 turns|
| ALFWorld |134 OOD episodes|GPT-5.4|low|30 interaction steps, seed42|
| TB2 |89 tasks|GPT-5.4|low|Original task deadline,60 turns|

All three tracks use4096 maximum completion tokens per request. A successful
transport response is required to report `gpt-5.4-2026-03-05` and valid usage.
Request-level transient retries are not whole-task score retries. The SkillsBench
base transport retains its recorded fallback/retry protocol; see `async_http.py`.
The wrappers do not add score-based retries or change verifiers/resources.

## Pool loading

The regular JSON loader requires a valid group-pool integrity hash and policy
source commitments. The optional compiled loader requires its `RECEIPT.json`
file/core commitments to match. It is the historical byte-identical reader;
its implementation temporarily substitutes module-level validators and leaves a
pool-specific canonical-hash wrapper. Use **one isolated Python worker per
trial**, not threaded concurrent retriever construction. An existing compiled
pool built for different core hashes is deliberately rejected; do not edit its
receipt to hide a mismatch. A JSON pool is easier for new public experiments.

The public source-root parameter changes paths shown to the agent, not skill
content. The physical skill tree must be mounted at that logical location in
container runs. Source-fidelity tests exercise an alternate root and reject
forged source content.

## What remains external

Benchmark tasks, images, complete skill library and graph/index must be obtained
under their original licenses. Official GoS evaluation modules are required for
ALFWorld. Historical verifier caches, exact-image transport adapters, deployment task-pack
builders, cleanup/recovery controllers and credential loaders are not global
plugins in this release. Those source snapshots remain in the companion archive.
They must be reviewed/adapted against any new environment; do not copy old hosts,
PIDs, output directories or replay old launch functions.

Offline tests validate imports, source fidelity, configuration semantics and
non-overwrite behavior. No Docker, simulator, paid model or full benchmark test
was run while packaging this release. Do not equate passing these tests with a
new reproduced benchmark score.

## Result accounting

Use the artifacts' selected-trial IDs/hashes to reconstruct the reported table.
The current GoSkills TB2 table contains44 retained successes plus45 conditional
zero-selected repeats, while the other methods were not rerun symmetrically.
Preserve both original and replacement tables and disclose this selection.
Missing verifier output, transport errors and environment failures are not valid
zero scores. Agent runtime excludes queue/container setup/verifier/cleanup;
input tokens include cached prompt tokens without double counting.

## Runtime versions

Core/offline tools support Python3.10+. Historical ALFWorld ran Python3.12.14;
TB2 host runtime ran Python3.13.14 with Harbor0.20.0. Use a separate compatible
evaluation environment; the core Python minimum does not guarantee every simulator
or Harbor dependency supports that same minimum. Version inventories are in configs/.
Install the relevant extra (`pip install -e ".[alfworld]"` or `pip install -e ".[terminal]"`)
plus upstream dependencies and assets; these are not fully resolved campaign locks.

## Portable five-method orchestration

The shared backend dispatches Vector and Graph to different official algorithms;
GoSkills D uses the frozen group pool. Vanilla preserves benchmark-specific full
library/catalog exposure, not a truncated retrieval approximation. Shared retrieval
settings remain top4, 1,800 characters per skill and9,000 context characters;
graph seed top-k5, no LLM query rewriting, real1,536-dimensional embeddings.
Source workspaces are copied per worker because the official storage may write.

SkillsBench preparation takes a raw task and preserves instruction/test/task.toml
bytes. Its host bridge intercepts a standalone named query in the original bash
tool protocol. The ordinary bash tool is unchanged. Guidance documents this
transport adaptation; query commands with shell chaining/pipes are rejected,
not evaluated as host shell commands. No provider credential is mounted into
containers. Vanilla and No Skills do not need retrieval evidence to score.

The new batch runner is sequential. It stops after an invalid trial, keeps all
valid zeros, and makes no automatic whole-task retries. Normalized receipts bind
model, usage, trace, verifier result and cleanup evidence; campaign STATUS binds
receipt hashes. Collection rejects changed or misplaced receipts and uses paths
relative to the archived campaign root. It produces no final mean for incomplete
method groups. See the root README for planning, execution and summary commands.

Use two Python3.12 environments: Harbor0.20's LiteLLM requires OpenAI SDK2,
while the pinned GoS fast-graphrag requires SDK1. The retrieval/ALFWorld stack
and Harbor stack have separately resolved Linux requirement files. The batch
configuration's retrieval_python controls ALFWorld and isolated retrieval helpers.
Do not dereference a venv Python symlink to its base interpreter. Linux is the
supported live target. Package/download
and schema tests do not invoke paid endpoints or certify task image availability.
