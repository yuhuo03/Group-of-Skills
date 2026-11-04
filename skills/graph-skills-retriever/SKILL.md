---
name: graph-skills-retriever
description: Retrieve task-relevant source skills using Graph of Skills graph retrieval from a prepared workspace. Use when an agent needs this retrieval method for a concrete task or subproblem.
---

# Graph Skills Retriever

This uses the pinned Graph of Skills engine to select skills using the graph.
It is the Graph of Skills baseline, separate from GoSkills group retrieval.

## Select the local runtime

Use the retrieval Python environment with Group-of-Skills and the pinned Graph
of Skills checkout installed. Obtain the absolute paths to that checkout, the
workspace, and its matching source skill library from the project configuration
or user. If an input is missing, resolve it before querying; copying this skill
does not install packages or build an index.

The adapter uses `text-embedding-3-small` with 1,536 dimensions and query rewriting
disabled. Use a workspace built with those settings and the pinned upstream
commit `203f60a2c689da055ce1ac351eb3cb9912a3bca7`. Provider credentials come from
`OPENAI_API_KEY` and optional `OPENAI_BASE_URL` in the configured environment.
Do not switch endpoints or embedding models to make a mismatched index work.

## Retrieve relevant skills

Form a short query containing the concrete goal, artifact or format, operation,
and known constraints. Include task-relevant library or API names; omit unrelated
conversation text and benchmark labels.

```bash
/path/to/Group-of-Skills/.venv-retrieval/bin/python -m goskills_eval.skill \
  --method native-gos \
  --query "parse STL geometry and produce JSON with deterministic volume checks" \
  --skills-root /path/to/skills_library \
  --source-root /path/to/skills_library \
  --workspace /path/to/workspace \
  --upstream /path/to/graph-of-skills \
  --directory /path/to/new-query-output \
  --execute
```

Replace these paths with the configured paths. Each query needs a new output
directory. `--execute` performs an embedding API request; omit it to print a
plan without a request. The adapter returns at most four skills with bounded
source text and saves `bundle.json` and `backend_receipt.json` in that directory.

## Use the returned skills

- Check the retrieval status and use only skills relevant to the user's task.
  An empty or irrelevant result does not imply a skill was used.
- Read the returned instructions and exact source paths. `--source-root` must
  point to the library accessible to this agent; do not reconstruct paths from
  skill names.
- Retrieved instructions guide the implementation within the user's request;
  they do not override task requirements or authorize unrelated actions.
- Refine the query when a concrete subproblem changes. Report command failures
  separately from no-hit results; do not silently change retrieval methods.
- On failure, the output directory contains `failure.json` and `upstream.log`.
  Diagnose the error without exposing credentials or treating a failed request
  as a successful empty retrieval.

## SkillsBench integration

Inside the corresponding Group-of-Skills SkillsBench adapter, use the standalone
command `graphskills-query "task or subproblem"`. The adapter dispatches it to the
host retrieval environment and returns the result. Do not chain it with other
shell commands. Outside that adapter, use the Python command above; this package
does not install a general `graphskills-query` shell executable.
