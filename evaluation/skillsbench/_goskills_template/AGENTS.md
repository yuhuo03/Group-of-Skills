# Task Environment

This environment contains a prebuilt **GoSkills** skill bundle.

## Required First Step

Before writing or editing solution code, retrieve a role-labeled GoSkills
execution context:

```bash
goskills-query "goal + artifact/format + operation/API + verifier-critical constraint"
```

Use only facts known from the task:

- concrete goal
- artifact, file format, or main object
- key operation, algorithm, API, or library
- verifier-critical constraint or invariant
- entity names, join keys, matching rules, and output conventions

Read the retrieval status first.

- If it says `Retrieval Status: NO_SKILL_HIT`, explicitly note that no relevant
  GoSkills group plan was found and continue without claiming skill usage.
- If it says `Retrieval Status: SKILL_HIT`, start from the **Anchor Group**.
  Follow `support`, `artifact`, and `verifier` groups only when they close a
  real gap. Treat `fallback` groups as alternatives if the anchor route fails.
  Do not combine groups connected by a `conflict` relation.

## Execution Priorities

1. Inspect visible tests/verifiers before implementation.
2. Preserve required output paths exactly.
3. Use the exact `Source:` paths returned by retrieval.
4. Check a returned skill's `scripts/` directory before implementing from scratch.
5. Keep the solution on the shortest verifier-aligned path.
6. For heavy framework tasks, run at most one compile or lightweight sanity check
   before finalizing unless the visible verifier requires more.
7. Prefer local files over web search or package installs.
