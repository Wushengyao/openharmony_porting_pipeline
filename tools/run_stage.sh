#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "用法：run_stage.sh <workspace_root> <stage> [out_dir]" >&2
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

timestamp() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log_msg() { local level="$1"; shift; printf '[%s] [%s] %s\n' "$(timestamp)" "${level}" "$*" | tee -a "${PIPELINE_LOG}"; }
log_file_state() {
  local label="$1" path="$2"
  if [[ -e "${path}" ]]; then
    log_msg INFO "${label}: ${path} ($(wc -c < "${path}") bytes)"
  else
    log_msg WARN "${label}: ${path} (missing)"
  fi
}

summarize_result() {
  local result_path="$1"
  python3 - "${result_path}" <<'PY' | tee -a "${PIPELINE_LOG}"
import json, sys
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
print(f"[result] stage={data.get('stage', path.stem)} status={data.get('status', 'unknown')} summary={(data.get('summary') or '')[:240]}")
for key in ["commit_records_count", "file_change_records_count", "binary_asset_records_count", "dirty_file_records_count", "repo_count", "changed_repo_count", "case_count", "case_candidate_count", "blocking_issue_count"]:
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
  08_meta_input_exporter) PROMPT="${PROMPTS_DIR}/08_meta_input_exporter.md"; SCHEMA="${SCHEMAS_DIR}/stage_result.schema.json";;
  10_porting_execution_assistant) PROMPT="${PROMPTS_DIR}/10_porting_execution_assistant.md"; SCHEMA="${SCHEMAS_DIR}/porting_execution_assistant.schema.json";;
  11_version_upgrade_porting) PROMPT="${PROMPTS_DIR}/11_version_upgrade_porting.md"; SCHEMA="${SCHEMAS_DIR}/version_upgrade_porting.schema.json";;
  *) echo "未知阶段：${STAGE}" >&2; exit 2;;
esac

CODEX_PROXY_URL="${CODEX_PROXY_URL:-http://127.0.0.1:7890}"
export http_proxy="${CODEX_PROXY_URL}" https_proxy="${CODEX_PROXY_URL}" all_proxy="${CODEX_PROXY_URL}"
export HTTP_PROXY="${CODEX_PROXY_URL}" HTTPS_PROXY="${CODEX_PROXY_URL}" ALL_PROXY="${CODEX_PROXY_URL}"
export no_proxy="${no_proxy:-localhost,127.0.0.1,::1}"
export NO_PROXY="${NO_PROXY:-${no_proxy}}"
export NODE_USE_ENV_PROXY=1
export PORTING_EXECUTION_MODE="${PORTING_EXECUTION_MODE:-plan-only}"
export PORTING_EXECUTION_PATCH_APPLY_MODE="${PORTING_EXECUTION_PATCH_APPLY_MODE:-none}"
export PORTING_EXECUTION_OUT_DIR="${PORTING_EXECUTION_OUT_DIR:-${OUT_DIR}}"
export PORTING_EXECUTION_ARTIFACT_DIR="${PORTING_EXECUTION_ARTIFACT_DIR:-${OUT_DIR}/08_execution_assistant}"
export PORTING_EXECUTION_SOURCE_OUTPUT="${PORTING_EXECUTION_SOURCE_OUTPUT:-${OUT_DIR}}"
export PORTING_EXECUTION_META_OUTPUT="${PORTING_EXECUTION_META_OUTPUT:-}"
export PORTING_EXECUTION_TARGET_PROFILE_SEED="${PORTING_EXECUTION_TARGET_PROFILE_SEED:-}"
export PORTING_EXECUTION_BUILD_LOG="${PORTING_EXECUTION_BUILD_LOG:-}"
export VERSION_UPGRADE_OLD_ORIGINAL="${VERSION_UPGRADE_OLD_ORIGINAL:-}"
export VERSION_UPGRADE_OLD_PORTED="${VERSION_UPGRADE_OLD_PORTED:-}"
export VERSION_UPGRADE_OLD_BASELINE_MANIFEST="${VERSION_UPGRADE_OLD_BASELINE_MANIFEST:-}"
export VERSION_UPGRADE_NEW_ORIGINAL="${VERSION_UPGRADE_NEW_ORIGINAL:-}"
export VERSION_UPGRADE_NEW_WORKSPACE="${VERSION_UPGRADE_NEW_WORKSPACE:-${WORKSPACE_ROOT}}"
export VERSION_UPGRADE_OUT_DIR="${VERSION_UPGRADE_OUT_DIR:-${OUT_DIR}}"
export VERSION_UPGRADE_ARTIFACT_DIR="${VERSION_UPGRADE_ARTIFACT_DIR:-${OUT_DIR}/09_version_upgrade}"
export VERSION_UPGRADE_TARGET_PROFILE_SEED="${VERSION_UPGRADE_TARGET_PROFILE_SEED:-}"
export VERSION_UPGRADE_BUILD_LOG="${VERSION_UPGRADE_BUILD_LOG:-}"
if [[ "${STAGE}" == "10_porting_execution_assistant" ]]; then
  mkdir -p "${PORTING_EXECUTION_ARTIFACT_DIR}"
fi
if [[ "${STAGE}" == "11_version_upgrade_porting" ]]; then
  mkdir -p "${VERSION_UPGRADE_ARTIFACT_DIR}"
fi

CODEX_BASE_ARGS=(--cd "${WORKSPACE_ROOT}" --sandbox workspace-write --skip-git-repo-check --ephemeral --json)
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_BASE_ARGS+=(--model "${CODEX_MODEL}")
fi
# shellcheck disable=SC2206
EXTRA_ARGS=(${CODEX_EXTRA_ARGS:-})

RESULT="${RESULT_DIR}/${STAGE}.json"
PENDING_RESULT="${RESULT_DIR}/${STAGE}.${RUN_ID}.pending.json"
LOG="${LOG_DIR}/${STAGE}.${RUN_ID}.ndjson"
VALIDATION_LOG="${LOG_DIR}/${STAGE}.${RUN_ID}.validation.log"
CANONICAL_LOG="${LOG_DIR}/${STAGE}.ndjson"
CANONICAL_VALIDATION_LOG="${LOG_DIR}/${STAGE}.validation.log"
FAILED_ATTEMPT_DIR="${LOG_DIR}/_failed_attempts/${STAGE}/${RUN_ID}"

archive_failed_attempt() {
  mkdir -p "${FAILED_ATTEMPT_DIR}"
  for path in "${LOG}" "${VALIDATION_LOG}" "${PENDING_RESULT}"; do
    if [[ -e "${path}" ]]; then
      mv -f "${path}" "${FAILED_ATTEMPT_DIR}/"
    fi
  done
  log_msg INFO "${STAGE}: archived failed attempt: ${FAILED_ATTEMPT_DIR}"
}

publish_success_attempt() {
  if [[ -e "${LOG}" ]]; then
    cp -f "${LOG}" "${CANONICAL_LOG}"
  fi
  if [[ -e "${VALIDATION_LOG}" ]]; then
    cp -f "${VALIDATION_LOG}" "${CANONICAL_VALIDATION_LOG}"
  fi
}

log_msg INFO "single-stage run_id=${RUN_ID}"
log_msg INFO "workspace=${WORKSPACE_ROOT}"
log_msg INFO "output_dir=${OUT_DIR}"
log_msg INFO "stage=${STAGE}"
log_msg INFO "pipeline_mode=${PIPELINE_MODE:-auto}"
log_msg INFO "prompt=${PROMPT}"
log_msg INFO "schema=${SCHEMA}"
log_msg INFO "codex=$(command -v codex || echo missing)"
log_msg INFO "codex_model=${CODEX_MODEL:-default}"
log_msg INFO "extra_args=${CODEX_EXTRA_ARGS:-<none>}"
log_msg INFO "proxy=${CODEX_PROXY_URL}"
log_msg INFO "deterministic flags: raw=${DETERMINISTIC_RAW_RECORD_EXTRACTOR:-1} dirty=${DETERMINISTIC_DIRTY_WORKSPACE_ANALYZER:-1} binary=${DETERMINISTIC_BINARY_ASSET_AUDITOR:-1} stats=${DETERMINISTIC_STATISTICS_QC:-1} semantic=${DETERMINISTIC_SEMANTIC_ANALYZER:-0} case=${DETERMINISTIC_CASE_KB:-0} skill=${DETERMINISTIC_SKILL_GENERATOR:-0} audit=${DETERMINISTIC_FINAL_AUDIT:-0} meta=${DETERMINISTIC_META_INPUT_EXPORTER:-1} upgrade=${DETERMINISTIC_VERSION_UPGRADE_PORTING:-1}"
log_file_state operator_context "${OUT_DIR}/00_config/operator_context.md"
log_file_state prompt "${PROMPT}"
log_file_state schema "${SCHEMA}"
rm -f "${PENDING_RESULT}"

START_EPOCH="$(date +%s)"
run_python_stage() {
  local label="$1" script="$2"
  log_msg INFO "${STAGE}: using deterministic ${script}"
  if python3 "${TOOLS_DIR}/${script}" --out "${OUT_DIR}" --stage-result "${PENDING_RESULT}" > "${LOG}" 2>&1; then
    END_EPOCH="$(date +%s)"
    log_msg INFO "${STAGE}: deterministic ${label} completed in $((END_EPOCH - START_EPOCH))s"
  else
    RC=$?
    END_EPOCH="$(date +%s)"
    log_msg ERROR "${STAGE}: deterministic ${label} failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
    log_file_state "stage log" "${LOG}"
    tail -n 120 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
    archive_failed_attempt
    exit "${RC}"
  fi
}

if [[ "${STAGE}" == "02_raw_record_extractor" && "${DETERMINISTIC_RAW_RECORD_EXTRACTOR:-1}" != "0" ]]; then
  run_python_stage "raw record extraction" "extract_raw_records.py"
elif [[ "${STAGE}" == "aux_dirty_workspace" && "${DETERMINISTIC_DIRTY_WORKSPACE_ANALYZER:-1}" != "0" ]]; then
  run_python_stage "dirty workspace analysis" "analyze_dirty_workspace.py"
elif [[ "${STAGE}" == "aux_binary_asset_auditor" && "${DETERMINISTIC_BINARY_ASSET_AUDITOR:-1}" != "0" ]]; then
  run_python_stage "binary asset audit" "audit_binary_assets.py"
elif [[ "${STAGE}" == "03_statistics_qc" && "${DETERMINISTIC_STATISTICS_QC:-1}" != "0" ]]; then
  run_python_stage "statistics aggregation" "aggregate_stats.py"
elif [[ "${STAGE}" == "04_semantic_analyzer" && "${DETERMINISTIC_SEMANTIC_ANALYZER:-0}" != "0" ]]; then
  run_python_stage "semantic analysis" "generate_semantic_analysis.py"
elif [[ "${STAGE}" == "05_case_kb_builder" && "${DETERMINISTIC_CASE_KB:-0}" != "0" ]]; then
  run_python_stage "case KB" "generate_case_kb.py"
elif [[ "${STAGE}" == "06_skill_generator" && "${DETERMINISTIC_SKILL_GENERATOR:-0}" != "0" ]]; then
  run_python_stage "Skill output" "generate_skill_output.py"
elif [[ "${STAGE}" == "07_final_auditor" && "${DETERMINISTIC_FINAL_AUDIT:-0}" != "0" ]]; then
  run_python_stage "final audit" "run_final_audit.py"
elif [[ "${STAGE}" == "08_meta_input_exporter" && "${DETERMINISTIC_META_INPUT_EXPORTER:-1}" != "0" ]]; then
  run_python_stage "meta input export" "export_meta_inputs.py"
elif [[ "${STAGE}" == "11_version_upgrade_porting" && "${DETERMINISTIC_VERSION_UPGRADE_PORTING:-1}" != "0" ]]; then
  log_msg INFO "${STAGE}: using deterministic compare_four_tree_upgrade.py"
  for required in VERSION_UPGRADE_OLD_PORTED VERSION_UPGRADE_NEW_ORIGINAL VERSION_UPGRADE_NEW_WORKSPACE; do
    if [[ -z "${!required}" ]]; then
      log_msg ERROR "${STAGE}: missing required environment variable ${required}"
      exit 2
    fi
  done
  UPGRADE_ARGS=(
    --old-ported "${VERSION_UPGRADE_OLD_PORTED}"
    --new-original "${VERSION_UPGRADE_NEW_ORIGINAL}"
    --new-workspace "${VERSION_UPGRADE_NEW_WORKSPACE}"
    --out "${VERSION_UPGRADE_OUT_DIR}"
    --artifact-root "${VERSION_UPGRADE_ARTIFACT_DIR}"
    --stage-result "${PENDING_RESULT}"
  )
  if [[ -n "${VERSION_UPGRADE_OLD_ORIGINAL}" ]]; then
    UPGRADE_ARGS+=(--old-original "${VERSION_UPGRADE_OLD_ORIGINAL}")
  fi
  if [[ -n "${VERSION_UPGRADE_OLD_BASELINE_MANIFEST}" ]]; then
    UPGRADE_ARGS+=(--old-baseline-manifest "${VERSION_UPGRADE_OLD_BASELINE_MANIFEST}")
  fi
  if [[ "${VERSION_UPGRADE_AUTO_OLD_BASELINE_MANIFEST:-1}" == "0" ]]; then
    UPGRADE_ARGS+=(--no-auto-old-baseline-manifest)
  fi
  if [[ -n "${VERSION_UPGRADE_FOCUS_PATHS:-}" ]]; then
    IFS=':' read -r -a UPGRADE_FOCUS_ARRAY <<< "${VERSION_UPGRADE_FOCUS_PATHS}"
    for focus_path in "${UPGRADE_FOCUS_ARRAY[@]}"; do
      [[ -n "${focus_path}" ]] && UPGRADE_ARGS+=(--focus-path "${focus_path}")
    done
  fi
  if [[ -n "${VERSION_UPGRADE_MAX_RECORDS:-}" ]]; then
    UPGRADE_ARGS+=(--max-records "${VERSION_UPGRADE_MAX_RECORDS}")
  fi
  if python3 "${TOOLS_DIR}/compare_four_tree_upgrade.py" "${UPGRADE_ARGS[@]}" > "${LOG}" 2>&1; then
    END_EPOCH="$(date +%s)"
    log_msg INFO "${STAGE}: deterministic four-tree comparison completed in $((END_EPOCH - START_EPOCH))s"
  else
    RC=$?
    END_EPOCH="$(date +%s)"
    log_msg ERROR "${STAGE}: deterministic four-tree comparison failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
    log_file_state "stage log" "${LOG}"
    tail -n 120 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
    archive_failed_attempt
    exit "${RC}"
  fi
elif codex exec \
  "${CODEX_BASE_ARGS[@]}" \
  "${EXTRA_ARGS[@]}" \
  --output-last-message "${PENDING_RESULT}" \
  --output-schema "${SCHEMA}" \
  - < "${PROMPT}" > "${LOG}" 2>&1; then
  END_EPOCH="$(date +%s)"
  log_msg INFO "${STAGE}: codex exec completed in $((END_EPOCH - START_EPOCH))s"
else
  RC=$?
  END_EPOCH="$(date +%s)"
  log_msg ERROR "${STAGE}: codex exec failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
  log_file_state "ndjson log" "${LOG}"
  log_file_state "pending result" "${PENDING_RESULT}"
  tail -n 120 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
  archive_failed_attempt
  exit "${RC}"
fi

log_file_state "ndjson log" "${LOG}"
log_file_state "pending result" "${PENDING_RESULT}"
summarize_result "${PENDING_RESULT}"
log_msg INFO "${STAGE}: validation_log=${VALIDATION_LOG}"
if python3 "${TOOLS_DIR}/validate_stage.py" --workspace "${WORKSPACE_ROOT}" --out "${OUT_DIR}" --stage "${STAGE}" --stage-result "${PENDING_RESULT}" 2>&1 | tee "${VALIDATION_LOG}"; then
  mv "${PENDING_RESULT}" "${RESULT}"
  log_file_state "promoted result" "${RESULT}"
  if python3 "${TOOLS_DIR}/render_chinese_summary.py" --out "${OUT_DIR}" --stage "${STAGE}" --stage-result "${RESULT}" 2>&1 | tee -a "${PIPELINE_LOG}"; then
    log_file_state "stage Chinese summary" "${RESULT_DIR}/${STAGE}.zh.md"
  else
    log_msg WARN "${STAGE}: Chinese summary rendering failed"
  fi
  publish_success_attempt
  log_msg INFO "${STAGE}: validation passed"
else
  RC=$?
  log_msg ERROR "${STAGE}: validation failed with exit_code=${RC}"
  tail -n 120 "${VALIDATION_LOG}" | tee -a "${PIPELINE_LOG}" || true
  archive_failed_attempt
  exit "${RC}"
fi
