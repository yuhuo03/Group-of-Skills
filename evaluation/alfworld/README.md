# ALFWorld Hook

The main GoSkills package is benchmark-agnostic. For ALFWorld-style interactive tasks, this folder provides a lightweight selector that maps a visible goal into a captain skill plus support skills for search, receptacle handling, device use, and final verification.

The selector is intentionally dependency-free so it can be imported by an external ALFWorld runner:

```python
from evaluation.alfworld.goskills_selector import select_skill_names

available = [
    "alfworld-clean-object",
    "alfworld-locate-target-object",
    "alfworld-receptacle-finder",
    "alfworld-task-verifier",
]
result = select_skill_names("put a clean apple in fridge", available, top_k=4)
print(result["summary"])
```

Full ALFWorld execution requires the external ALFWorld environment and assets. This artifact keeps those assets out of the anonymous code ZIP.
