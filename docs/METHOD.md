# GoSkills D implementation in the GPT-5.4 release

The `goskills/` package is the **byte-identical ten-module snapshot** from the frozen SkillsBench `goskills_group_eval_v3` implementation also bound by the TB2 `terminalbench2_gpt54_recovery_v5` freeze. The per-file hashes and two source-freeze hashes are in `provenance/CORE_SOURCE.json`. Release packaging does not change the method policy. ALFWorld's domain adapter is separate; the method name does not imply an identical simulator integration.

The previous release's `group_graph.py`, `text.py`, and `cli.py` API is not retained as if it were the current experimental method. This release follows its repository organization, while using the actual D code and the versioned graph/pool/bundle schemas below.

## Pipeline and retained improvements

1. **Directed source graph.** The offline constructor accepts skill texts with typed edges. `dep` means prerequisite → consumer and `workflow` means earlier → later. Alternative and semantic relations are symmetric; other positive relations retain direction. Explicit incompatibility suppresses positive relations for the same pair.
2. **Reusable groups.** Query-independent groups preserve leads and support roles; each group contains at most three skills. Facet similarity uses a rare-first inverted-prefix candidate join followed by exact Jaccard checks, rather than creating an indiscriminate shared-format clique.
3. **Seeds.** Lexical mode uses binary TF–IDF cosine with separator normalization and deterministic tie-breaking. Both query and document lengths are normalized. External seed evidence is an explicitly separate configuration.
4. **Bounded selection.** The online policy activates and expands groups, accounts for relevance/coverage/anchor/check/connectivity/redundancy/negative/cost features, preserves eligible leads and incoming prerequisite/preprocessor skills, and limits groups, skills, and backfill.
5. **Source-preserving presentation.** `presentation.py` extracts complete source sections with ancestor scope and statically detected Python example prerequisites. It never executes skill examples. Decision-tree or over-budget procedures fall back to a disclosed source prefix. It does not generate replacement skill instructions.
6. **Visible coverage.** Coverage is credited from presented text, not hidden metadata. Uncovered explicit requirements remain in `DEBT`. Every emitted contract has `START`, `SUPPORT`, `CHECK`, `AVOID`, `SKILLS`, and `DEBT` in that order.
7. **Trace and checks.** Bundles contain selected groups, skill payloads, source spans, feature/selection traces, and coverage debt. `validate_bundle` checks that the declared payloads, anchor, budgets, and debt match the rendered context.

The source comments retain their historical reconstruction/assumption identifiers. They identify this implementation's development lineage, not proof that its decisions improve every task. In particular, observed benchmark feedback was used during D development; this release does not assert a blind held-out method-selection protocol.

## Frozen defaults

| Parameter | Value |
|---|---:|
| Presented skills (`top_n`) | 4 |
| Lexical seed limit (`seed_top_k`) | 4 |
| Skill body cap | 1,800 characters |
| Full rendered-context cap | 9,000 characters |
| Members per group | 3 |
| Selected groups | 3 |
| Backfill cap | 2 |
| Neighbor limit | 2 |
| Group affinity threshold | 0.35 |
| Prior/anchor coefficients | 0.05 / 0.18 |
| Group/support/skill acceptance minima | 0.14 / 0.10 / 0.10 |
| Seed mode | `lexical` |
| Policy identifier | `paper-reconstruction-v1` |

These are character caps, not tokenizer budgets. Context accounting includes paths and the contract. The fixed feature vectors/weights are in `config.py`; configuration validation rejects unknown keys, non-finite values, and unsupported bounds. Larger custom budgets are not silently accepted as the same method.

## Data contracts

- **Graph:** `schema_version: 1`, `kind: goskills_graph`, nonempty `skills` list, and optional `edges`. Each skill has unique `id`, `name`, `body`, and safe library-relative `source_path`; optional `description`, `text`, and metadata preserve source information. Edge types: `dep`, `workflow`, `semantic`, `alternative`, `artifact`, `visible-check`, `fallback`, `incompat`.
- **Pool:** produced only by `build_pool` / CLI `build`, with skills, groups, typed group relations, configuration, source-graph hash, construction-source hashes and content integrity hash. Manually edited pools are rejected. Keep the pool with the code version that created it.
- **Bundle:** produced by `Retriever.query` / CLI `query`, including query-visible schema, selection trace, presented source payloads, rendered contract and remaining coverage debt. Treat task text, skill text and tool outputs as data, not release maintainer instructions.

`examples/minimal_graph.json` is synthetic tutorial data with this exact graph schema. It is not the experimental skill library or a benchmark fixture used for scores.

## Entry points

```bash
python -m goskills build --graph examples/minimal_graph.json --output /tmp/goskills-pool.json
python -m goskills query --pool /tmp/goskills-pool.json --query "Parse STL and output JSON" --json
python -m goskills validate-bundle path/to/query-output.json
```

Use `--output-json` with `query` to save the bundle. Use fresh output paths: atomic writes refuse to replace existing records. The build/query/validate path uses only Python's standard library and makes no provider calls.

### Optional official GoS export

`export-native` is a strict compatibility adapter for the verified historical directed GoS checkpoint. It requires a clean upstream checkout at commit `203f60a2c689da055ce1ac351eb3cb9912a3bca7`, the corresponding GoS dependencies (including `hnswlib` and `numpy`), source skill library, native vector workspace, and verified indexing ledger. Set the checkout explicitly rather than relying on machine-specific discovery:

```bash
export GOSKILLS_OFFICIAL_ROOT=/path/to/graph-of-skills
python -m goskills export-native \
  --workspace /path/to/native-workspace \
  --skills-root /path/to/skills_2000 \
  --index-run-dir /path/to/verified-index-run \
  --output /path/to/new-graph.json
```

The export operates through the official loader on a scratch copy, validates graph direction, source text, vector dimension and indexing evidence, and disables provider calls. It rejects arbitrary or incomplete old workspaces. It is not a general downloader or a promise that any upstream version can load the frozen experiment assets.

## Release validation

```bash
python -m unittest discover -s tests -p 'test_core*.py' -v
```

The ten offline checks cover frozen-source identity, reordered-input determinism, unmatched-query behavior, real rendered-context budgets, source-span extraction, debt tampering rejection, pool tampering rejection, duplicate source rejection, refusal to overwrite records, and the documented CLI round trip. These checks are software regression checks, not new benchmark runs or evidence of a higher score.
