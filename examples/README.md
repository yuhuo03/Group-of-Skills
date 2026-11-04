# Offline retrieval example

The five short synthetic skills and four typed edges in `minimal_graph.json` demonstrate the real GoSkills D schema. They are not benchmark data, the experimental 2,000-skill library, or evidence for the reported scores. No API key, Docker container or network access is required.

From the repository root:

```bash
python -m goskills build --graph examples/minimal_graph.json --output /tmp/goskills-demo-pool.json
python -m goskills query --pool /tmp/goskills-demo-pool.json --query "Use trimesh to parse STL and write JSON with deterministic unit tests." --output-json /tmp/goskills-demo-answer.json
python -m goskills validate-bundle /tmp/goskills-demo-answer.json
```

Choose fresh output filenames for each run: the CLI intentionally refuses to overwrite prior files. `query --json` prints the full selection trace and payload provenance. The default prints the bounded execution contract.

Python API:

```python
from goskills.io import read_json
from goskills.groups import build_pool
from goskills.config import validate_config
from goskills.retrieval import Retriever
from goskills.validation import validate_bundle

pool = build_pool(read_json("examples/minimal_graph.json"), validate_config())
bundle = Retriever(pool).query("Parse STL and produce JSON with unit tests.")
validate_bundle(bundle)
print(bundle["rendered_context"])
```
