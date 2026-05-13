#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: run_stage.sh <workspace_root> <stage> [out_dir]" >&2
  exit 2
fi
WORKSPACE_ROOT="$(cd "$1" && pwd)"
STAGE="$2"
OUT_DIR="${3:-${WORKSPACE_ROOT}/porting_knowledge_output}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROMPTS_DIR="${PIPELINE_DIR}/prompts"
SCHEMAS_DIR="${PIPELINE_DIR}/schemas"
TOOLS_DIR="${PIPELINE_DIR}/tools"
LOG_DIR="${OUT_DIR}/_codex_stage_logs"
RESULT_DIR="${OUT_DIR}/_stage_results"
RUN_ID="$(date '+%Y%m%d_%H%M%S')"
PIPELINE_LOG="${LOG_DIR}/run_stage_${STAGE}_${RUN_ID}.log"
mkdir -p "${OUT_DIR}" "${LOG_DIR}" "${RESULT_DIR}"

timestamp() {
  date '+%Y-%m-%dT%H:%M:%S%z'
}

log_msg() {
  local level="$1"
  shift
  printf '[%s] [%s] %s\n' "$(timestamp)" "${level}" "$*" | tee -a "${PIPELINE_LOG}"
}

log_file_state() {
  local label="$1"
  local path="$2"
  if [[ -e "${path}" ]]; then
    local size
    size="$(wc -c < "${path}")"
    log_msg "INFO" "${label}: ${path} (${size} bytes)"
  else
    log_msg "WARN" "${label}: ${path} (missing)"
  fi
}

summarize_result() {
  local result_path="$1"
  python3 - "${result_path}" <<'PY' | tee -a "${PIPELINE_LOG}"
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.exists():
    print(f"[result] missing: {path}")
    raise SystemExit(0)
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception as exc:
    print(f"[result] invalid json: {path}: {exc}")
    raise SystemExit(0)
status = data.get("status", "unknown")
stage = data.get("stage", path.stem)
summary = data.get("summary", "")
print(f"[result] stage={stage} status={status} summary={summary[:240]}")
outputs = data.get("output_files_written") or []
if outputs:
    print(f"[result] output_files_written={len(outputs)}")
for key in [
    "commit_records_count",
    "file_change_records_count",
    "binary_asset_records_count",
    "dirty_file_records_count",
    "repo_count",
    "changed_repo_count",
]:
    if key in data:
        print(f"[result] {key}={data[key]}")
PY
}

case "${STAGE}" in
  00_scope_classifier) PROMPT="${PROMPTS_DIR}/00_scope_classifier.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  01_repo_baseline_extractor) PROMPT="${PROMPTS_DIR}/01_repo_baseline_extractor.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  02_raw_record_extractor) PROMPT="${PROMPTS_DIR}/02_raw_record_extractor.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  aux_dirty_workspace) PROMPT="${PROMPTS_DIR}/aux_dirty_workspace.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  aux_binary_asset_auditor) PROMPT="${PROMPTS_DIR}/aux_binary_asset_auditor.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  03_statistics_qc) PROMPT="${PROMPTS_DIR}/03_statistics_qc.md"; SCHEMA="${SCHEMAS_DIR}/statistics_summary.schema.json";;
  04_semantic_analyzer) PROMPT="${PROMPTS_DIR}/04_semantic_analyzer.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  05_case_kb_builder) PROMPT="${PROMPTS_DIR}/05_case_kb_builder.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  06_skill_generator) PROMPT="${PROMPTS_DIR}/06_skill_generator.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  07_final_auditor) PROMPT="${PROMPTS_DIR}/07_final_auditor.md"; SCHEMA="${SCHEMAS_DIR}/audit_result.schema.json";;
  *) echo "unknown stage: ${STAGE}" >&2; exit 2;;
esac

CODEX_PROXY_URL="${CODEX_PROXY_URL:-http://127.0.0.1:7890}"
export http_proxy="${CODEX_PROXY_URL}"
export https_proxy="${CODEX_PROXY_URL}"
export all_proxy="${CODEX_PROXY_URL}"
export HTTP_PROXY="${CODEX_PROXY_URL}"
export HTTPS_PROXY="${CODEX_PROXY_URL}"
export ALL_PROXY="${CODEX_PROXY_URL}"
export no_proxy="${no_proxy:-localhost,127.0.0.1,::1}"
export NO_PROXY="${NO_PROXY:-${no_proxy}}"
export NODE_USE_ENV_PROXY=1

CODEX_BASE_ARGS=(--cd "${WORKSPACE_ROOT}" --sandbox workspace-write --skip-git-repo-check --ephemeral --json)
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_BASE_ARGS+=(--model "${CODEX_MODEL}")
fi
# shellcheck disable=SC2206
EXTRA_ARGS=(${CODEX_EXTRA_ARGS:-})

RESULT="${RESULT_DIR}/${STAGE}.json"
PENDING_RESULT="${RESULT_DIR}/${STAGE}.${RUN_ID}.pending.json"
LOG="${LOG_DIR}/${STAGE}.ndjson"
VALIDATION_LOG="${LOG_DIR}/${STAGE}.validation.log"

log_msg "INFO" "Single-stage run_id=${RUN_ID}"
log_msg "INFO" "workspace=${WORKSPACE_ROOT}"
log_msg "INFO" "output_dir=${OUT_DIR}"
log_msg "INFO" "stage=${STAGE}"
log_msg "INFO" "prompt=${PROMPT}"
log_msg "INFO" "schema=${SCHEMA}"
log_msg "INFO" "codex=$(command -v codex)"
log_msg "INFO" "codex_model=${CODEX_MODEL:-default}"
log_msg "INFO" "extra_args=${CODEX_EXTRA_ARGS:-<none>}"
log_msg "INFO" "proxy=${CODEX_PROXY_URL}"
log_file_state "prompt" "${PROMPT}"
log_file_state "schema" "${SCHEMA}"
rm -f "${PENDING_RESULT}"

START_EPOCH="$(date +%s)"
if [[ "${STAGE}" == "03_statistics_qc" && "${DETERMINISTIC_STATISTICS_QC:-1}" != "0" ]]; then
  log_msg "INFO" "${STAGE}: using deterministic aggregate_stats.py"
  if python3 "${TOOLS_DIR}/aggregate_stats.py" \
    --out "${OUT_DIR}" \
    --stage-result "${PENDING_RESULT}" > "${LOG}" 2>&1; then
    END_EPOCH="$(date +%s)"
    log_msg "INFO" "${STAGE}: deterministic aggregation completed in $((END_EPOCH - START_EPOCH))s"
  else
    RC=$?
    END_EPOCH="$(date +%s)"
    log_msg "ERROR" "${STAGE}: deterministic aggregation failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
    log_file_state "aggregation log" "${LOG}"
    log_msg "ERROR" "${STAGE}: last 80 lines from ${LOG}"
    tail -n 80 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
    exit "${RC}"
  fi
elif [[ "${STAGE}" == "04_semantic_analyzer" && "${DETERMINISTIC_SEMANTIC_ANALYZER:-1}" != "0" ]]; then
  log_msg "INFO" "${STAGE}: using deterministic generate_semantic_analysis.py"
  if python3 "${TOOLS_DIR}/generate_semantic_analysis.py" \
    --out "${OUT_DIR}" \
    --stage-result "${PENDING_RESULT}" > "${LOG}" 2>&1; then
    END_EPOCH="$(date +%s)"
    log_msg "INFO" "${STAGE}: deterministic semantic analysis completed in $((END_EPOCH - START_EPOCH))s"
  else
    RC=$?
    END_EPOCH="$(date +%s)"
    log_msg "ERROR" "${STAGE}: deterministic semantic analysis failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
    log_file_state "semantic log" "${LOG}"
    log_msg "ERROR" "${STAGE}: last 80 lines from ${LOG}"
    tail -n 80 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
    exit "${RC}"
  fi
elif [[ "${STAGE}" == "05_case_kb_builder" && "${DETERMINISTIC_CASE_KB:-1}" != "0" ]]; then
  log_msg "INFO" "${STAGE}: using deterministic generate_case_kb.py"
  if python3 "${TOOLS_DIR}/generate_case_kb.py" \
    --out "${OUT_DIR}" \
    --stage-result "${PENDING_RESULT}" > "${LOG}" 2>&1; then
    END_EPOCH="$(date +%s)"
    log_msg "INFO" "${STAGE}: deterministic case KB completed in $((END_EPOCH - START_EPOCH))s"
  else
    RC=$?
    END_EPOCH="$(date +%s)"
    log_msg "ERROR" "${STAGE}: deterministic case KB failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
    log_file_state "case KB log" "${LOG}"
    log_msg "ERROR" "${STAGE}: last 80 lines from ${LOG}"
    tail -n 80 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
    exit "${RC}"
  fi
elif [[ "${STAGE}" == "06_skill_generator" && "${DETERMINISTIC_SKILL_GENERATOR:-1}" != "0" ]]; then
  log_msg "INFO" "${STAGE}: using deterministic generate_skill_output.py"
  if python3 "${TOOLS_DIR}/generate_skill_output.py" \
    --out "${OUT_DIR}" \
    --stage-result "${PENDING_RESULT}" > "${LOG}" 2>&1; then
    END_EPOCH="$(date +%s)"
    log_msg "INFO" "${STAGE}: deterministic Skill output completed in $((END_EPOCH - START_EPOCH))s"
  else
    RC=$?
    END_EPOCH="$(date +%s)"
    log_msg "ERROR" "${STAGE}: deterministic Skill output failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
    log_file_state "Skill output log" "${LOG}"
    log_msg "ERROR" "${STAGE}: last 80 lines from ${LOG}"
    tail -n 80 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
    exit "${RC}"
  fi
elif [[ "${STAGE}" == "07_final_auditor" && "${DETERMINISTIC_FINAL_AUDIT:-1}" != "0" ]]; then
  log_msg "INFO" "${STAGE}: using deterministic run_final_audit.py"
  if python3 "${TOOLS_DIR}/run_final_audit.py" \
    --out "${OUT_DIR}" \
    --stage-result "${PENDING_RESULT}" > "${LOG}" 2>&1; then
    END_EPOCH="$(date +%s)"
    log_msg "INFO" "${STAGE}: deterministic final audit completed in $((END_EPOCH - START_EPOCH))s"
  else
    RC=$?
    END_EPOCH="$(date +%s)"
    log_msg "ERROR" "${STAGE}: deterministic final audit failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
    log_file_state "final audit log" "${LOG}"
    log_msg "ERROR" "${STAGE}: last 80 lines from ${LOG}"
    tail -n 80 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
    exit "${RC}"
  fi
elif codex exec \
  "${CODEX_BASE_ARGS[@]}" \
  "${EXTRA_ARGS[@]}" \
  --output-last-message "${PENDING_RESULT}" \
  --output-schema "${SCHEMA}" \
  - < "${PROMPT}" > "${LOG}" 2>&1; then
  END_EPOCH="$(date +%s)"
  log_msg "INFO" "${STAGE}: codex exec completed in $((END_EPOCH - START_EPOCH))s"
else
  RC=$?
  END_EPOCH="$(date +%s)"
  log_msg "ERROR" "${STAGE}: codex exec failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
  log_file_state "ndjson log" "${LOG}"
  log_file_state "pending result" "${PENDING_RESULT}"
  log_msg "ERROR" "${STAGE}: last 80 lines from ${LOG}"
  tail -n 80 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
  exit "${RC}"
fi

log_file_state "ndjson log" "${LOG}"
log_file_state "pending result" "${PENDING_RESULT}"
summarize_result "${PENDING_RESULT}"
log_msg "INFO" "${STAGE}: validation_log=${VALIDATION_LOG}"
if python3 "${TOOLS_DIR}/validate_stage.py" --workspace "${WORKSPACE_ROOT}" --out "${OUT_DIR}" --stage "${STAGE}" --stage-result "${PENDING_RESULT}" 2>&1 | tee "${VALIDATION_LOG}"; then
  mv "${PENDING_RESULT}" "${RESULT}"
  log_file_state "promoted result" "${RESULT}"
  log_msg "INFO" "${STAGE}: validation passed"
else
  RC=$?
  log_msg "ERROR" "${STAGE}: validation failed with exit_code=${RC}"
  log_msg "ERROR" "${STAGE}: last 80 lines from ${VALIDATION_LOG}"
  tail -n 80 "${VALIDATION_LOG}" | tee -a "${PIPELINE_LOG}" || true
  exit "${RC}"
fi
