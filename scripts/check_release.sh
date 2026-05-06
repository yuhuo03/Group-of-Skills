#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "[check] unit tests"
python -m pytest tests -q

echo "[check] bytecode compilation"
python -m compileall -q goskills gos evaluation/skillsbench evaluation/alfworld

echo "[check] shell syntax"
for script in scripts/*.sh; do
  bash -n "$script"
done

echo "[check] paper defaults"
python - <<'PY'
from goskills.group_graph import CANDIDATE_POOL_CAP, MAX_GROUP_SIZE
from goskills.retrieval import MAX_BACKFILL_SKILLS, MAX_SELECTED_GROUPS

assert MAX_GROUP_SIZE == 3
assert CANDIDATE_POOL_CAP == 32
assert MAX_SELECTED_GROUPS == 3
assert MAX_BACKFILL_SKILLS == 2
PY

scan_common_args=(
  --hidden
  --glob '!scripts/check_release.sh'
  --glob '!.git/**'
  --glob '!*.zip'
  --glob '!*.png'
  --glob '!*.jpg'
  --glob '!*.jpeg'
  --glob '!*.pdf'
  --glob '!*.pyc'
  --glob '!__pycache__/**'
  --glob '!.pytest_cache/**'
)

echo "[check] stale internal names"
stale_patterns=(
  "Group""Graph"
  "group""graph"
  "GROUP""GRAPH"
  "go""sg"
  "group""graph-query"
  "Skill""Coalition"
  "skill""coalition"
  "Group-of-Skills-""Graph"
)
for pattern in "${stale_patterns[@]}"; do
  if rg -n "${scan_common_args[@]}" "$pattern" .; then
    echo "Stale name found: ${pattern}" >&2
    exit 1
  fi
done

echo "[check] local paths and common secret formats"
secret_patterns=(
  "/home/""lthpc"
  "/nvme-""data"
  "38""\\.147"
  "G-""Designer"
  "G""Designer"
  "sk-[A-Za-z0-9]{20,}"
  "ghp_[A-Za-z0-9_]{20,}"
)
for pattern in "${secret_patterns[@]}"; do
  if rg -n "${scan_common_args[@]}" "$pattern" .; then
    echo "Local path or secret-looking value found: ${pattern}" >&2
    exit 1
  fi
done

echo "[check] ok"
