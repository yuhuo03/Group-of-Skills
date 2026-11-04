# Contributing

Use Python 3.10 or later for core retrieval development. Full benchmark evaluation
uses Python 3.12 and the separate environments described in the README.

```bash
uv venv --python 3.12 --seed .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
```

The tests use local synthetic fixtures and do not call model APIs or run benchmarks.
Add a behavioral test when changing retrieval or evaluation behavior. Keep method
logic separate from benchmark environment adapters.

Do not commit API keys, local configuration, downloaded inputs, generated outputs,
or virtual environments. Live evaluation is separate from development tests and
requires configured credentials and benchmark resources.
