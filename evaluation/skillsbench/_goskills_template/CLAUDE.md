# Task Environment

This environment provides `goskills-query`.

Run it before coding:

```bash
goskills-query "goal + artifact/format + operation/API + verifier-critical constraint"
```

The output is a GoSkills role-labeled execution context with `support`,
`artifact`, `verifier`, `fallback`, and `conflict` relation evidence.

- Start with the Anchor Group.
- Use support/artifact/verifier groups only for concrete verifier gaps.
- Treat fallback groups as alternatives, not extra work.
- Never combine groups marked as conflicting.
- Use exact `Source:` paths and inspect local scripts first.
