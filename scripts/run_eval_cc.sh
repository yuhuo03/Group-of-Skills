#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="${COMPARE_WORKSPACE_ROOT:-$(cd "${REPO_ROOT}/.." && pwd)}"
GRAPH_ROOT="${COMPARE_GRAPH_ROOT:-${GRAPH_OF_SKILLS_ROOT:-${WORKSPACE_ROOT}/graph-of-skills}}"
GOSKILLS_ROOT="${COMPARE_GOSKILLS_ROOT:-${REPO_ROOT}}"
TASKS_ROOT="${COMPARE_TASKS_ROOT:-${GRAPH_ROOT}/evaluation/skillsbench/generated_table1_skills1000/tasks_graph_skills}"
SOURCE_BUNDLE="${COMPARE_SOURCE_BUNDLE:-${GRAPH_ROOT}/evaluation/skillsbench/generated_table1_skills1000/shared/graphskills_bundle.json}"

TIMESTAMP="${COMPARE_TIMESTAMP:-$(date '+%Y-%m-%d__gos-cc-%H-%M-%S')}"
OUTPUT_ROOT="${COMPARE_OUTPUT_ROOT:-${SCRIPT_DIR}/generated_compare_v2/${TIMESTAMP}}"
LOG_DIR="${SCRIPT_DIR}/logs/gos_cc_${TIMESTAMP}"
RUN_LOG="${LOG_DIR}/run.log"
METRICS_CSV="${SCRIPT_DIR}/logs/gos_cc_metrics_${TIMESTAMP}.csv"
METRICS_MD="${SCRIPT_DIR}/logs/gos_cc_metrics_${TIMESTAMP}.md"

PYTHON_BIN="${COMPARE_PYTHON_BIN:-${PYTHON:-${GRAPH_ROOT}/.venv/bin/python}}"
HARBOR_BIN="${COMPARE_HARBOR_BIN:-${GRAPH_ROOT}/.venv/bin/harbor}"
REPO_ENV_FILE="${COMPARE_ENV_FILE:-${GRAPH_ROOT}/.env}"
DOCKER_CONFIG="${COMPARE_DOCKER_CONFIG:-${REPO_ROOT}/.docker}"

mkdir -p "${LOG_DIR}" "${SCRIPT_DIR}/jobs" "${SCRIPT_DIR}/configs" "${DOCKER_CONFIG}"
export DOCKER_CONFIG
export PYTHONPATH="${SCRIPT_DIR}:${GOSKILLS_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

TASKS_CSV="$(
  find "${TASKS_ROOT}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
    | sort \
    | paste -sd, -
)"
if [[ -z "${TASKS_CSV}" ]]; then
  echo "No SkillBench tasks found under ${TASKS_ROOT}" >&2
  exit 1
fi

TASKS_CSV="${COMPARE_TASKS:-${TASKS_CSV}}"
IFS=',' read -r -a TASKS <<< "${TASKS_CSV}"

export SKILLBENCH_RUNTIME_ROOT="${SKILLBENCH_RUNTIME_ROOT:-${REPO_ROOT}/.skillbench-runtime}"
export TMPDIR="${TMPDIR:-${SKILLBENCH_RUNTIME_ROOT}/tmp}"
export TMP="${TMP:-${TMPDIR}}"
export TEMP="${TEMP:-${TMPDIR}}"
export DOCKER_TMPDIR="${DOCKER_TMPDIR:-${SKILLBENCH_RUNTIME_ROOT}/docker-tmp}"

SKILLSET_NAME="${COMPARE_SKILLSET_NAME:-skills_1000}"
MODEL_NAME="${COMPARE_MODEL:-ccsonnet4.5}"
DEFAULT_DIRECT_BASE_URL="https://api.openai.com/v1"
DIRECT_BASE_URL="${COMPARE_DIRECT_BASE_URL:-${DIRECT_BASE_URL:-${OPENAI_BASE_URL:-${DEFAULT_DIRECT_BASE_URL}}}}"
DIRECT_API_ENV_KEY="${COMPARE_DIRECT_API_ENV_KEY:-OPENAI_API_KEY}"
REASONING_EFFORT="${COMPARE_CODEX_REASONING_EFFORT:-${COMPARE_REASONING_EFFORT:-low}}"
N_ATTEMPTS="${COMPARE_N_ATTEMPTS:-1}"
CONCURRENCY="${COMPARE_CONCURRENCY:-1}"
MAX_RETRIES="${COMPARE_MAX_RETRIES:-0}"
AGENT_TIMEOUT_SEC="${COMPARE_AGENT_TIMEOUT_SEC:-900}"
AGENT_SETUP_TIMEOUT_SEC="${COMPARE_AGENT_SETUP_TIMEOUT_SEC:-120}"
FORCE_BUILD="${COMPARE_FORCE_BUILD:-false}"
ROOT_MIN_FREE_KB="${COMPARE_ROOT_MIN_FREE_KB:-1048576}"

log() {
  printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*" | tee -a "${RUN_LOG}"
}

has_real_secret() {
  local value="${1:-}"
  [[ -n "$value" ]] || return 1
  [[ "$value" != your-* ]] || return 1
  [[ "$value" != optional-* ]] || return 1
  case "$value" in
    \<*\>) return 1 ;;
  esac
  return 0
}

load_repo_env() {
  [[ -f "$REPO_ENV_FILE" ]] || return 0
  while IFS= read -r line; do
    line="$(printf '%s' "$line" | sed -E 's/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*/\1=/')"
    [[ -z "$line" ]] && continue
    key="${line%%=*}"
    value="${line#*=}"
    if [[ "$value" =~ ^\".*\"$ ]] || [[ "$value" =~ ^\'.*\'$ ]]; then
      value="${value:1:${#value}-2}"
    fi
    if [[ -z ${!key+x} ]]; then
      export "$key=$value"
    fi
  done < <(grep -v -E '^\s*#|^\s*$' "$REPO_ENV_FILE")

  if has_real_secret "${COMPARE_DIRECT_API_KEY:-}"; then
    export OPENAI_API_KEY="${COMPARE_DIRECT_API_KEY}"
  elif has_real_secret "${DIRECT_API_KEY:-}"; then
    export OPENAI_API_KEY="${DIRECT_API_KEY}"
  elif has_real_secret "${API_KEY:-}"; then
    export OPENAI_API_KEY="${API_KEY}"
  elif has_real_secret "${GOS_LLM_OPENAI_API_KEY:-}"; then
    export OPENAI_API_KEY="${GOS_LLM_OPENAI_API_KEY}"
  fi
  if [[ -z "${OPENAI_BASE_URL:-}" ]]; then
    export OPENAI_BASE_URL="${DIRECT_BASE_URL}"
  fi
}

check_prereqs() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
  fi
  [[ -n "$PYTHON_BIN" && -x "$PYTHON_BIN" ]] || { echo "Missing python. Set COMPARE_PYTHON_BIN." >&2; exit 1; }
  if [[ ! -x "$HARBOR_BIN" ]]; then
    HARBOR_BIN="$(command -v harbor || true)"
  fi
  [[ -n "$HARBOR_BIN" && -x "$HARBOR_BIN" ]] || { echo "Missing harbor. Set COMPARE_HARBOR_BIN or install Graph-of-Skills benchmark dependencies." >&2; exit 1; }
  [[ -d "${GRAPH_ROOT}/data/skillsets/${SKILLSET_NAME}" ]] || { echo "Missing skillset ${SKILLSET_NAME}" >&2; exit 1; }
  command -v docker >/dev/null 2>&1 || { echo "Missing docker" >&2; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo "Missing docker compose plugin" >&2; exit 1; }
  load_repo_env
  has_real_secret "${OPENAI_API_KEY:-}" || { echo "Missing OPENAI_API_KEY/COMPARE_DIRECT_API_KEY" >&2; exit 1; }
}

root_free_kb() {
  df -Pk / | awk 'NR==2 {print $4}'
}

prune_if_needed() {
  local free_kb
  free_kb="$(root_free_kb)"
  if [[ "${free_kb}" =~ ^[0-9]+$ ]] && (( free_kb < ROOT_MIN_FREE_KB )); then
    log "Root free space ${free_kb}KB below threshold ${ROOT_MIN_FREE_KB}KB; pruning Docker caches."
    docker system prune -af >> "${RUN_LOG}" 2>&1 || true
  fi
}

prepare_dataset() {
  local task_args=()
  local task
  for task in "${TASKS[@]}"; do
    task="$(printf '%s' "$task" | xargs)"
    [[ -n "$task" ]] || continue
    task_args+=(--task "$task")
  done
  log "Generating GoSkills dataset at ${OUTPUT_ROOT}"
  rm -rf "${OUTPUT_ROOT}"
  "$PYTHON_BIN" "${SCRIPT_DIR}/../evaluation/skillsbench/gen_benchmark.py" \
    --graph-of-skills-root "${GRAPH_ROOT}" \
    --skillset-name "${SKILLSET_NAME}" \
    --tasks-root "${TASKS_ROOT}" \
    --source-bundle "${SOURCE_BUNDLE}" \
    --output-root "${OUTPUT_ROOT}" \
    "${task_args[@]}" >> "${RUN_LOG}" 2>&1
}

create_config() {
  local task_name="$1"
  local config_file="$2"
  cat > "${config_file}" <<EOF
job_name: compare-${task_name}-${TIMESTAMP}
jobs_dir: jobs
n_attempts: ${N_ATTEMPTS}
timeout_multiplier: 1.0
debug: false
orchestrator:
  type: local
  n_concurrent_trials: ${CONCURRENCY}
  quiet: false
  retry:
    max_retries: ${MAX_RETRIES}
    include_exceptions: null
    exclude_exceptions:
    - VerifierTimeoutError
    - BadRequestError
    - RateLimitError
    - AgentTimeoutError
    wait_multiplier: 1.0
    min_wait_sec: 1.0
    max_wait_sec: 60.0
  kwargs: {}
environment:
  type: docker
  import_path: null
  force_build: ${FORCE_BUILD}
  delete: true
  override_cpus: null
  override_memory_mb: null
  override_storage_mb: null
  override_gpus: null
  kwargs: {}
verifier:
  override_timeout_sec: null
  max_timeout_sec: null
  disable: false
metrics: []
agents:
- name: direct-api-bash
  import_path: agent:DirectAPIBashAgent
  model_name: ${MODEL_NAME}
  override_timeout_sec: ${AGENT_TIMEOUT_SEC}
  override_setup_timeout_sec: ${AGENT_SETUP_TIMEOUT_SEC}
  max_timeout_sec: null
  kwargs:
    prompt_template_path: ${REPO_ROOT}/evaluation/skillsbench/prompt_templates/goskills_retrieval.j2
    base_url: ${DIRECT_BASE_URL}
    api_env_key: ${DIRECT_API_ENV_KEY}
    reasoning_effort: ${REASONING_EFFORT}
    max_turns: ${COMPARE_MAX_TURNS:-60}
    tool_timeout_sec: ${COMPARE_TOOL_TIMEOUT_SEC:-180}
    max_observation_chars: ${COMPARE_MAX_OBSERVATION_CHARS:-12000}
    max_completion_tokens: ${COMPARE_MAX_COMPLETION_TOKENS:-4096}
datasets:
- task_names:
  - ${task_name}
  path: ${OUTPUT_ROOT}/tasks_goskills
EOF
}

run_tasks() {
  local task config_dir config_file jobs_root
  for raw_task in "${TASKS[@]}"; do
    task="$(printf '%s' "$raw_task" | xargs)"
    [[ -n "$task" ]] || continue
    [[ -d "${OUTPUT_ROOT}/tasks_goskills/${task}" ]] || { echo "Missing generated task ${task}" >&2; exit 1; }
    config_dir="${SCRIPT_DIR}/configs/compare-${task}-${TIMESTAMP}"
    jobs_root="${SCRIPT_DIR}/jobs/compare-${task}-${TIMESTAMP}"
    mkdir -p "${config_dir}" "${jobs_root}"
    config_file="${config_dir}/goskills.yaml"
    create_config "$task" "$config_file"
    log "Running ${task} / goskills"
    prune_if_needed
    if "$HARBOR_BIN" run --yes --config "$config_file" -o "${jobs_root}/goskills" >> "${RUN_LOG}" 2>&1; then
      log "Finished ${task} / goskills"
    else
      local status=$?
      log "Failed ${task} / goskills with exit code ${status}; continuing so the remaining tasks can be measured."
    fi
    prune_if_needed
  done
}

collect_metrics() {
  log "Collecting metrics"
  "$PYTHON_BIN" "${SCRIPT_DIR}/../evaluation/skillsbench/collect_metrics.py" \
    --jobs-root "${SCRIPT_DIR}/jobs" \
    --job-glob "compare-*-${TIMESTAMP}" \
    --output "${METRICS_CSV}" \
    --summary "${METRICS_MD}" >> "${RUN_LOG}" 2>&1
  log "Metrics CSV: ${METRICS_CSV}"
  log "Metrics summary: ${METRICS_MD}"
  cat "${METRICS_MD}" | tee -a "${RUN_LOG}"
}

main() {
  check_prereqs
  {
    echo "[start] $(date '+%Y-%m-%d %H:%M:%S')"
    echo "[timestamp] ${TIMESTAMP}"
    echo "[task_count] $(tr ',' '\n' <<<"${TASKS_CSV}" | sed '/^$/d' | wc -l)"
    echo "[model] ${MODEL_NAME}"
    echo "[direct_base_url] ${DIRECT_BASE_URL}"
    echo "[source_bundle] ${SOURCE_BUNDLE}"
    echo "[output_root] ${OUTPUT_ROOT}"
    echo "[metrics_csv] ${METRICS_CSV}"
    echo "[metrics_md] ${METRICS_MD}"
    docker info --format '[docker_root] {{.DockerRootDir}}' 2>/dev/null || true
    df -h / /tmp "${REPO_ROOT}" || true
  } | tee -a "${RUN_LOG}"
  prepare_dataset
  run_tasks
  collect_metrics
  echo "[done] $(date '+%Y-%m-%d %H:%M:%S')" | tee -a "${RUN_LOG}"
}

main "$@"
