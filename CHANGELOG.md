# Changelog

## 0.2.0rc2 — Complete five-method entrypoints (2026-11-04)

- All five methods on SkillsBench, ALFWorld and TB2; real pinned baseline engines.
- Fresh SkillsBench task-pack preparation and host retrieval bridge.
- Sequential batch plans, independent trial outputs, checked token/runtime receipts,
  portable result collection and setup doctor; no automatic score retries.
- Complete input preparation guide and134 hashed ALFWorld game mappings.
- Frozen core and all historical result data remain unchanged.
- Offline fake-provider/Harbor tests only; no new API or benchmark executions.

## 0.2.0rc1 — GPT-5.4 release candidate (2026-11-04)

- Uses the frozen candidate-D implementation actually shared by the GPT-5.4
  SkillsBench, ALFWorld integration and TB2 experiments, replacing the older
  recovered release's `group_graph.py` / `retrieval.py` interface.
- Preserves the ten frozen core module bytes and their provenance. The core's
  internal historical version remains 0.1.0; distribution version labels this
  new packaging, not a newly tuned retrieval algorithm.
- Separates portable evaluation integrations from historical server recovery
  scripts; adds benchmark-specific documentation and offline tests.
- Includes the selected GPT-5.4 three-benchmark numeric data, offline table
  reproduction, original TB2 comparison and full45 replacement mapping.
- Keeps raw traces and native task artifacts in a separate artifact release.
- Removes legacy six-model tables and deployment-specific launch commands from
  the public-facing entry point. Does not claim new benchmark measurements.

This release does not preserve compatibility with `goskills.group_graph` or the
old `goskills-query` API. Use `python -m goskills --help` for the current CLI.
