#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_MODE="${PIPELINE_MODE:-auto}"
PIPELINE_EXPORT_META="${PIPELINE_EXPORT_META:-1}"
POSITIONAL_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)
      PIPELINE_MODE="${2:-}"
      if [[ -z "${PIPELINE_MODE}" ]]; then
        echo "--mode 需要指定 auto 或 collab" >&2
        exit 2
      fi
      shift 2
      ;;
    --auto)
      PIPELINE_MODE="auto"
      shift
      ;;
    --export-meta)
      PIPELINE_EXPORT_META="1"
      shift
      ;;
    --no-export-meta)
      PIPELINE_EXPORT_META="0"
      shift
      ;;
    --collab|--human|--interactive)
      PIPELINE_MODE="collab"
      shift
      ;;
    -h|--help)
      echo "用法：run_pipeline.sh [--mode auto|collab] [--export-meta|--no-export-meta] [workspace_root] [out_dir]" >&2
      exit 0
      ;;
    *)
      POSITIONAL_ARGS+=("$1")
      shift
      ;;
  esac
done
case "${PIPELINE_MODE}" in
  auto|collab|human|interactive) ;;
  *) echo "未知的 PIPELINE_MODE/--mode：${PIPELINE_MODE}" >&2; exit 2;;
esac
if [[ "${PIPELINE_MODE}" == "human" || "${PIPELINE_MODE}" == "interactive" ]]; then
  PIPELINE_MODE="collab"
fi
WORKSPACE_ROOT="${POSITIONAL_ARGS[0]:-$PWD}"
OUT_DIR="${POSITIONAL_ARGS[1]:-${WORKSPACE_ROOT}/porting_knowledge_output}"
PIPELINE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROMPTS_DIR="${PIPELINE_DIR}/prompts"
SCHEMAS_DIR="${PIPELINE_DIR}/schemas"
TOOLS_DIR="${PIPELINE_DIR}/tools"
LOG_DIR="${OUT_DIR}/_codex_stage_logs"
RESULT_DIR="${OUT_DIR}/_stage_results"
RUN_ID="$(date '+%Y%m%d_%H%M%S')"
PIPELINE_LOG="${LOG_DIR}/pipeline_${RUN_ID}.log"

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

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH" >&2
  exit 127
fi

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

log_msg "INFO" "Pipeline run_id=${RUN_ID}"
log_msg "INFO" "workspace=${WORKSPACE_ROOT}"
log_msg "INFO" "output_dir=${OUT_DIR}"
log_msg "INFO" "pipeline_dir=${PIPELINE_DIR}"
log_msg "INFO" "pipeline_mode=${PIPELINE_MODE}"
log_msg "INFO" "export_meta=${PIPELINE_EXPORT_META}"
log_msg "INFO" "codex=$(command -v codex)"
log_msg "INFO" "codex_model=${CODEX_MODEL:-default}"
log_msg "INFO" "extra_args=${CODEX_EXTRA_ARGS:-<none>}"
log_msg "INFO" "proxy=${CODEX_PROXY_URL}"
log_msg "INFO" "deterministic flags: raw=${DETERMINISTIC_RAW_RECORD_EXTRACTOR:-1} dirty=${DETERMINISTIC_DIRTY_WORKSPACE_ANALYZER:-1} binary=${DETERMINISTIC_BINARY_ASSET_AUDITOR:-1} stats=${DETERMINISTIC_STATISTICS_QC:-1} semantic=${DETERMINISTIC_SEMANTIC_ANALYZER:-0} case=${DETERMINISTIC_CASE_KB:-0} skill=${DETERMINISTIC_SKILL_GENERATOR:-0} audit=${DETERMINISTIC_FINAL_AUDIT:-0} meta=${DETERMINISTIC_META_INPUT_EXPORTER:-1}"

OPERATOR_CONTEXT_LOG="${LOG_DIR}/operator_context_${RUN_ID}.log"
log_msg "INFO" "collecting operator context: mode=${PIPELINE_MODE}"
if python3 "${TOOLS_DIR}/collect_operator_context.py" --out "${OUT_DIR}" --mode "${PIPELINE_MODE}" > "${OPERATOR_CONTEXT_LOG}" 2>&1; then
  log_file_state "operator_context_md" "${OUT_DIR}/00_config/operator_context.md"
  log_file_state "operator_context_json" "${OUT_DIR}/00_config/operator_context.json"
  log_file_state "operator_context_log" "${OPERATOR_CONTEXT_LOG}"
else
  rc=$?
  log_msg "ERROR" "operator context collection failed with exit_code=${rc}"
  log_file_state "operator_context_log" "${OPERATOR_CONTEXT_LOG}"
  tail -n 80 "${OPERATOR_CONTEXT_LOG}" | tee -a "${PIPELINE_LOG}" || true
  exit "${rc}"
fi

run_stage() {
  local stage="$1"
  local prompt="$2"
  local schema="$3"
  local result="${RESULT_DIR}/${stage}.json"
  local pending_result="${RESULT_DIR}/${stage}.${RUN_ID}.pending.json"
  local log="${LOG_DIR}/${stage}.${RUN_ID}.ndjson"
  local validation_log="${LOG_DIR}/${stage}.${RUN_ID}.validation.log"
  local canonical_log="${LOG_DIR}/${stage}.ndjson"
  local canonical_validation_log="${LOG_DIR}/${stage}.validation.log"
  local failed_attempt_dir="${LOG_DIR}/_failed_attempts/${stage}/${RUN_ID}"
  local start_epoch
  local end_epoch
  local elapsed
  start_epoch="$(date +%s)"

  archive_failed_attempt() {
    mkdir -p "${failed_attempt_dir}"
    for path in "${log}" "${validation_log}" "${pending_result}"; do
      if [[ -e "${path}" ]]; then
        mv -f "${path}" "${failed_attempt_dir}/"
      fi
    done
    log_msg "INFO" "${stage}: archived failed attempt: ${failed_attempt_dir}"
  }

  publish_success_attempt() {
    if [[ -e "${log}" ]]; then
      cp -f "${log}" "${canonical_log}"
    fi
    if [[ -e "${validation_log}" ]]; then
      cp -f "${validation_log}" "${canonical_validation_log}"
    fi
  }

  log_msg "INFO" "===== Running ${stage} ====="
  log_msg "INFO" "${stage}: prompt=${prompt}"
  log_msg "INFO" "${stage}: schema=${schema}"
  log_msg "INFO" "${stage}: ndjson_log=${log}"
  log_msg "INFO" "${stage}: pending_result=${pending_result}"
  log_msg "INFO" "${stage}: final_result=${result}"
  log_file_state "${stage}: prompt" "${prompt}"
  log_file_state "${stage}: schema" "${schema}"
  rm -f "${pending_result}"

  if [[ "${stage}" == "02_raw_record_extractor" && "${DETERMINISTIC_RAW_RECORD_EXTRACTOR:-1}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic extract_raw_records.py"
    if python3 "${TOOLS_DIR}/extract_raw_records.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic raw extraction completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic raw extraction failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: raw extraction log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif [[ "${stage}" == "aux_dirty_workspace" && "${DETERMINISTIC_DIRTY_WORKSPACE_ANALYZER:-1}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic analyze_dirty_workspace.py"
    if python3 "${TOOLS_DIR}/analyze_dirty_workspace.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic dirty workspace analysis completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic dirty workspace analysis failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: dirty workspace log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif [[ "${stage}" == "aux_binary_asset_auditor" && "${DETERMINISTIC_BINARY_ASSET_AUDITOR:-1}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic audit_binary_assets.py"
    if python3 "${TOOLS_DIR}/audit_binary_assets.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic binary asset audit completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic binary asset audit failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: binary asset audit log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif [[ "${stage}" == "03_statistics_qc" && "${DETERMINISTIC_STATISTICS_QC:-1}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic aggregate_stats.py"
    if python3 "${TOOLS_DIR}/aggregate_stats.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic aggregation completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic aggregation failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: aggregation log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif [[ "${stage}" == "04_semantic_analyzer" && "${DETERMINISTIC_SEMANTIC_ANALYZER:-0}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic generate_semantic_analysis.py"
    if python3 "${TOOLS_DIR}/generate_semantic_analysis.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic semantic analysis completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic semantic analysis failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: semantic log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif [[ "${stage}" == "05_case_kb_builder" && "${DETERMINISTIC_CASE_KB:-0}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic generate_case_kb.py"
    if python3 "${TOOLS_DIR}/generate_case_kb.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic case KB completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic case KB failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: case KB log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif [[ "${stage}" == "06_skill_generator" && "${DETERMINISTIC_SKILL_GENERATOR:-0}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic generate_skill_output.py"
    if python3 "${TOOLS_DIR}/generate_skill_output.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic Skill output completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic Skill output failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: Skill output log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif [[ "${stage}" == "07_final_auditor" && "${DETERMINISTIC_FINAL_AUDIT:-0}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic run_final_audit.py"
    if python3 "${TOOLS_DIR}/run_final_audit.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic final audit completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic final audit failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: final audit log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif [[ "${stage}" == "08_meta_input_exporter" && "${DETERMINISTIC_META_INPUT_EXPORTER:-1}" != "0" ]]; then
    log_msg "INFO" "${stage}: using deterministic export_meta_inputs.py"
    if python3 "${TOOLS_DIR}/export_meta_inputs.py" \
      --out "${OUT_DIR}" \
      --stage-result "${pending_result}" > "${log}" 2>&1; then
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "INFO" "${stage}: deterministic meta input export completed in ${elapsed}s"
    else
      local rc=$?
      end_epoch="$(date +%s)"
      elapsed="$((end_epoch - start_epoch))"
      log_msg "ERROR" "${stage}: deterministic meta input export failed with exit_code=${rc} after ${elapsed}s"
      log_file_state "${stage}: meta input export log" "${log}"
      log_msg "ERROR" "${stage}: last 80 lines from ${log}"
      tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
      archive_failed_attempt
      return "${rc}"
    fi
  elif codex exec \
    "${CODEX_BASE_ARGS[@]}" \
    "${EXTRA_ARGS[@]}" \
    --output-last-message "${pending_result}" \
    --output-schema "${schema}" \
    - < "${prompt}" > "${log}" 2>&1; then
    end_epoch="$(date +%s)"
    elapsed="$((end_epoch - start_epoch))"
    log_msg "INFO" "${stage}: codex exec completed in ${elapsed}s"
  else
    local rc=$?
    end_epoch="$(date +%s)"
    elapsed="$((end_epoch - start_epoch))"
    log_msg "ERROR" "${stage}: codex exec failed with exit_code=${rc} after ${elapsed}s"
    log_file_state "${stage}: ndjson log" "${log}"
    log_file_state "${stage}: pending result" "${pending_result}"
    log_msg "ERROR" "${stage}: last 80 lines from ${log}"
    tail -n 80 "${log}" | tee -a "${PIPELINE_LOG}" || true
    archive_failed_attempt
    return "${rc}"
  fi

  log_file_state "${stage}: ndjson log" "${log}"
  log_file_state "${stage}: pending result" "${pending_result}"
  summarize_result "${pending_result}"
  log_msg "INFO" "${stage}: validation_log=${validation_log}"
  if python3 "${TOOLS_DIR}/validate_stage.py" \
    --workspace "${WORKSPACE_ROOT}" \
    --out "${OUT_DIR}" \
    --stage "${stage}" \
    --stage-result "${pending_result}" 2>&1 | tee "${validation_log}"; then
    mv "${pending_result}" "${result}"
    log_file_state "${stage}: promoted result" "${result}"
    if python3 "${TOOLS_DIR}/render_chinese_summary.py" --out "${OUT_DIR}" --stage "${stage}" --stage-result "${result}" 2>&1 | tee -a "${PIPELINE_LOG}"; then
      log_file_state "${stage}: Chinese summary" "${RESULT_DIR}/${stage}.zh.md"
    else
      log_msg "WARN" "${stage}: Chinese summary rendering failed"
    fi
    publish_success_attempt
    log_msg "INFO" "${stage}: validation passed"
  else
    local rc=$?
    log_msg "ERROR" "${stage}: validation failed with exit_code=${rc}"
    log_msg "ERROR" "${stage}: last 80 lines from ${validation_log}"
    tail -n 80 "${validation_log}" | tee -a "${PIPELINE_LOG}" || true
    archive_failed_attempt
    return "${rc}"
  fi
}

run_stage "00_scope_classifier" "${PROMPTS_DIR}/00_scope_classifier.md" "${SCHEMAS_DIR}/stage_result.schema.json"
run_stage "01_repo_baseline_extractor" "${PROMPTS_DIR}/01_repo_baseline_extractor.md" "${SCHEMAS_DIR}/stage_result.schema.json"
run_stage "02_raw_record_extractor" "${PROMPTS_DIR}/02_raw_record_extractor.md" "${SCHEMAS_DIR}/stage_result.schema.json"
run_stage "aux_dirty_workspace" "${PROMPTS_DIR}/aux_dirty_workspace.md" "${SCHEMAS_DIR}/stage_result.schema.json"
run_stage "aux_binary_asset_auditor" "${PROMPTS_DIR}/aux_binary_asset_auditor.md" "${SCHEMAS_DIR}/stage_result.schema.json"
run_stage "03_statistics_qc" "${PROMPTS_DIR}/03_statistics_qc.md" "${SCHEMAS_DIR}/statistics_summary.schema.json"
run_stage "04_semantic_analyzer" "${PROMPTS_DIR}/04_semantic_analyzer.md" "${SCHEMAS_DIR}/stage_result.schema.json"
run_stage "05_case_kb_builder" "${PROMPTS_DIR}/05_case_kb_builder.md" "${SCHEMAS_DIR}/stage_result.schema.json"
run_stage "06_skill_generator" "${PROMPTS_DIR}/06_skill_generator.md" "${SCHEMAS_DIR}/stage_result.schema.json"
run_stage "07_final_auditor" "${PROMPTS_DIR}/07_final_auditor.md" "${SCHEMAS_DIR}/audit_result.schema.json"
if [[ "${PIPELINE_EXPORT_META}" == "1" ]]; then
  run_stage "08_meta_input_exporter" "${PROMPTS_DIR}/08_meta_input_exporter.md" "${SCHEMAS_DIR}/stage_result.schema.json"
else
  log_msg "INFO" "08_meta_input_exporter skipped because PIPELINE_EXPORT_META=${PIPELINE_EXPORT_META}"
fi

if python3 "${TOOLS_DIR}/render_chinese_summary.py" --out "${OUT_DIR}" --overall 2>&1 | tee -a "${PIPELINE_LOG}"; then
  log_file_state "overall Chinese summary" "${OUT_DIR}/06_audit/pipeline_summary.zh.md"
  log_file_state "stage Chinese overview" "${OUT_DIR}/06_audit/stage_results.zh.md"
else
  log_msg "WARN" "overall Chinese summary rendering failed"
fi

echo "Pipeline finished. Output: ${OUT_DIR}"
echo "流水线已完成。输出目录：${OUT_DIR}"
echo "中文总体摘要：${OUT_DIR}/06_audit/pipeline_summary.zh.md"
