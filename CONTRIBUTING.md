# Contributing

Use Python 3.10+ for core retrieval and offline table reproduction.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
python scripts/reproduce_table.py --check
python scripts/check_release.py
```

Keep core algorithm changes distinct from evaluation transport changes. Preserve
source provenance; never edit a historical result to match a new implementation.
New live runs need new output directories and an explicit experiment protocol.
Do not commit API keys, .env files, raw traces, downloaded task assets or caches.
Test with synthetic fixtures before running optional paid benchmarks. CI only
runs offline checks. See LICENSE_STATUS.md before distributing modifications.
