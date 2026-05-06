---
name: goskills-retriever
description: Retrieve a GoSkills role-labeled execution context from a prebuilt skill bundle. Use when the task benefits from anchor selection, support expansion, visible checks, and conflict pruning instead of a flat skill list.
inputs:
  - task description or subproblem summary
outputs:
  - role-labeled execution context with source paths
compatibility:
  - claude-code
  - codex
  - gemini-cli
allowed-tools:
  - shell
---

# Purpose

Use this skill when the environment provides `goskills-query`.

`goskills-query` returns:

- one query-conditioned **anchor group**
- a bounded GoSkills group plan expanded on the group graph `H`
- typed relation evidence: `support`, `artifact`, `verifier`, `fallback`, and `conflict`
- pruning diagnostics for ability coverage, execution coherence, and conflict constraints
- a compact ordered set of presented atomic skills to inspect or execute

# Retrieve A Coalition

Construct the query from retrieval-critical facts:

- concrete goal
- artifact or file format
- key operation, algorithm, API, or library
- verifier-critical constraint or invariant
- entity names, join keys, matching rules, and output conventions

Run:

```bash
goskills-query "short specific query with goal + artifact + operation + constraint"
```

Useful flags:

```bash
goskills-query "parse branching dialogue script into graph export" --top-n 4
goskills-query "xlsx formulas inside pptx preserve workbook semantics" --json
```

# How To Use The Result

1. Read the retrieval status first.
2. If it says `NO_SKILL_HIT`, continue without claiming skill usage.
3. If it says `SKILL_HIT`, start from the **Anchor Group**.
4. Follow `support` and `artifact` groups only when they close a real coverage gap.
5. Use `verifier` groups for the smallest visible check.
6. Treat `fallback` groups as alternatives, not extra parallel work.
7. Do not combine groups marked by `conflict`; use the selected conflict-free plan.
8. Use the exact `Source:` paths returned by retrieval.
