#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROMPT="${PIPELINE_DIR}/prompts/10_porting_execution_assistant.md"
SCHEMA="${PIPELINE_DIR}/schemas/porting_execution_assistant.schema.json"
TOOLS_DIR="${PIPELINE_DIR}/tools"

EXECUTION_MODE="plan-only"
PATCH_APPLY_MODE="none"
SOURCE_OUTPUT=""
META_OUTPUT=""
TARGET_PROFILE_SEED=""
TARGET_SOURCE_ROOT=""
BUILD_LOG=""
OUT_DIR=""
POSITIONAL_ARGS=()

usage() {
  cat >&2 <<'EOF'
用法：run_porting_execution_assistant.sh [options] [workspace_root] [out_dir]

Options:
  --plan-only                      默认模式，只生成执行计划和跟进清单
  --mode plan-only                 P0 仅支持 plan-only
  --patch-apply-mode none|plan-only
                                   P0 不生成或应用补丁
  --source-output DIR              已有单场景 porting_knowledge_output，默认等于 out_dir
  --meta-output DIR                可选 cross-scenario openharmony_porting_meta_output
  --target-profile FILE            可选目标画像种子 YAML
  --target-source-root DIR         可选目标参考源码树；只读提取证据，不写入当前 workspace
  --build-log FILE                 可选已有构建日志，只用于 triage，不代表 boot/runtime/test
  --out DIR                        输出目录，默认 <workspace_root>/porting_knowledge_output
  -h, --help                       显示帮助
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --plan-only)
      EXECUTION_MODE="plan-only"
      PATCH_APPLY_MODE="none"
      shift
      ;;
    --mode)
      EXECUTION_MODE="${2:-}"
      if [[ -z "${EXECUTION_MODE}" ]]; then
        echo "--mode 需要指定 plan-only" >&2
        exit 2
      fi
      shift 2
      ;;
    --patch-apply-mode)
      PATCH_APPLY_MODE="${2:-}"
      if [[ -z "${PATCH_APPLY_MODE}" ]]; then
        echo "--patch-apply-mode 需要指定 none 或 plan-only" >&2
        exit 2
      fi
      shift 2
      ;;
    --source-output)
      SOURCE_OUTPUT="${2:-}"
      shift 2
      ;;
    --meta-output)
      META_OUTPUT="${2:-}"
      shift 2
      ;;
    --target-profile)
      TARGET_PROFILE_SEED="${2:-}"
      shift 2
      ;;
    --target-source-root)
      TARGET_SOURCE_ROOT="${2:-}"
      shift 2
      ;;
    --build-log)
      BUILD_LOG="${2:-}"
      shift 2
      ;;
    --out)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      POSITIONAL_ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ "${EXECUTION_MODE}" != "plan-only" ]]; then
  echo "P0 仅支持 --mode plan-only；不会自动生成高风险补丁或处理外部依赖。" >&2
  exit 2
fi
case "${PATCH_APPLY_MODE}" in
  none|plan-only) ;;
  *)
    echo "P0 仅支持 --patch-apply-mode none|plan-only。" >&2
    exit 2
    ;;
esac

WORKSPACE_ROOT="${POSITIONAL_ARGS[0]:-$PWD}"
WORKSPACE_ROOT="$(cd "${WORKSPACE_ROOT}" && pwd)"
if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="${POSITIONAL_ARGS[1]:-${WORKSPACE_ROOT}/porting_knowledge_output}"
fi
if [[ -n "${TARGET_SOURCE_ROOT}" ]]; then
  if [[ ! -d "${TARGET_SOURCE_ROOT}" ]]; then
    echo "--target-source-root must be an existing directory: ${TARGET_SOURCE_ROOT}" >&2
    exit 2
  fi
  TARGET_SOURCE_ROOT="$(cd "${TARGET_SOURCE_ROOT}" && pwd)"
fi
if [[ -z "${SOURCE_OUTPUT}" ]]; then
  SOURCE_OUTPUT="${OUT_DIR}"
fi
if [[ -z "${META_OUTPUT}" && -d "${WORKSPACE_ROOT}/openharmony_porting_meta_output" ]]; then
  META_OUTPUT="${WORKSPACE_ROOT}/openharmony_porting_meta_output"
fi
META_OUTPUT_INPUT="${META_OUTPUT}"
if [[ -n "${META_OUTPUT}" && -f "${META_OUTPUT}" ]]; then
  case "${META_OUTPUT}" in
    *.zip)
      META_CACHE_PARENT="${OUT_DIR}/_meta_output_cache"
      mkdir -p "${META_CACHE_PARENT}"
      META_OUTPUT="$(
        python3 - "${META_OUTPUT_INPUT}" "${META_CACHE_PARENT}" <<'PY'
import shutil
import sys
import zipfile
from pathlib import Path

zip_path = Path(sys.argv[1]).resolve()
cache_parent = Path(sys.argv[2]).resolve()
cache_dir = cache_parent / zip_path.stem
tmp_dir = cache_parent / f".{zip_path.stem}.extracting"
if tmp_dir.exists():
    shutil.rmtree(tmp_dir)
tmp_dir.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(zip_path) as archive:
    archive.extractall(tmp_dir)
candidates = [
    path
    for path in tmp_dir.rglob("*")
    if path.is_dir()
    and ((path / "cross_scenario_result.json").is_file() or (path / "02_patterns").is_dir())
]
root = sorted(candidates, key=lambda item: len(item.parts))[0] if candidates else tmp_dir
if cache_dir.exists():
    shutil.rmtree(cache_dir)
shutil.move(str(root), str(cache_dir))
shutil.rmtree(tmp_dir, ignore_errors=True)
print(cache_dir)
PY
      )"
      ;;
    *)
      echo "--meta-output must be a directory or .zip file: ${META_OUTPUT}" >&2
      exit 2
      ;;
  esac
fi

LOG_DIR="${OUT_DIR}/_codex_stage_logs"
RESULT_DIR="${OUT_DIR}/_stage_results"
ARTIFACT_DIR="${OUT_DIR}/08_execution_assistant"
RUN_ID="$(date '+%Y%m%d_%H%M%S')"
PIPELINE_LOG="${LOG_DIR}/porting_execution_assistant_${RUN_ID}.log"
STAGE="10_porting_execution_assistant"
PENDING_RESULT="${RESULT_DIR}/${STAGE}.${RUN_ID}.pending.json"
RESULT="${RESULT_DIR}/${STAGE}.json"
LOG="${LOG_DIR}/${STAGE}.${RUN_ID}.ndjson"
VALIDATION_LOG="${LOG_DIR}/${STAGE}.${RUN_ID}.validation.log"
CANONICAL_LOG="${LOG_DIR}/${STAGE}.ndjson"
CANONICAL_VALIDATION_LOG="${LOG_DIR}/${STAGE}.validation.log"
FAILED_ATTEMPT_DIR="${LOG_DIR}/_failed_attempts/${STAGE}/${RUN_ID}"

mkdir -p "${OUT_DIR}" "${LOG_DIR}" "${RESULT_DIR}" "${ARTIFACT_DIR}"

timestamp() { date '+%Y-%m-%dT%H:%M:%S%z'; }
log_msg() { local level="$1"; shift; printf '[%s] [%s] %s\n' "$(timestamp)" "${level}" "$*" | tee -a "${PIPELINE_LOG}"; }
log_file_state() {
  local label="$1" path="$2"
  if [[ -d "${path}" ]]; then
    local child_count
    child_count="$(find "${path}" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d ' ')"
    log_msg INFO "${label}: ${path} (directory, ${child_count} direct entries)"
  elif [[ -f "${path}" ]]; then
    log_msg INFO "${label}: ${path} ($(wc -c < "${path}") bytes)"
  elif [[ -e "${path}" ]]; then
    log_msg INFO "${label}: ${path} (exists)"
  else
    log_msg WARN "${label}: ${path} (missing)"
  fi
}
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

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found in PATH" >&2
  exit 127
fi

CODEX_PROXY_URL="${CODEX_PROXY_URL:-http://127.0.0.1:7890}"
export http_proxy="${CODEX_PROXY_URL}" https_proxy="${CODEX_PROXY_URL}" all_proxy="${CODEX_PROXY_URL}"
export HTTP_PROXY="${CODEX_PROXY_URL}" HTTPS_PROXY="${CODEX_PROXY_URL}" ALL_PROXY="${CODEX_PROXY_URL}"
export no_proxy="${no_proxy:-localhost,127.0.0.1,::1}"
export NO_PROXY="${NO_PROXY:-${no_proxy}}"
export NODE_USE_ENV_PROXY=1

export PORTING_EXECUTION_MODE="${EXECUTION_MODE}"
export PORTING_EXECUTION_PATCH_APPLY_MODE="${PATCH_APPLY_MODE}"
export PORTING_EXECUTION_OUT_DIR="${OUT_DIR}"
export PORTING_EXECUTION_ARTIFACT_DIR="${ARTIFACT_DIR}"
export PORTING_EXECUTION_SOURCE_OUTPUT="${SOURCE_OUTPUT}"
export PORTING_EXECUTION_META_OUTPUT="${META_OUTPUT}"
export PORTING_EXECUTION_TARGET_PROFILE_SEED="${TARGET_PROFILE_SEED}"
export PORTING_EXECUTION_TARGET_SOURCE_ROOT="${TARGET_SOURCE_ROOT}"
export PORTING_EXECUTION_BUILD_LOG="${BUILD_LOG}"

CODEX_BASE_ARGS=(--cd "${WORKSPACE_ROOT}" --sandbox workspace-write --skip-git-repo-check --ephemeral --json)
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_BASE_ARGS+=(--model "${CODEX_MODEL}")
fi
# shellcheck disable=SC2206
EXTRA_ARGS=(${CODEX_EXTRA_ARGS:-})

log_msg INFO "execution assistant run_id=${RUN_ID}"
log_msg INFO "workspace=${WORKSPACE_ROOT}"
log_msg INFO "output_dir=${OUT_DIR}"
log_msg INFO "artifact_dir=${ARTIFACT_DIR}"
log_msg INFO "source_output=${SOURCE_OUTPUT}"
if [[ -n "${META_OUTPUT_INPUT}" && "${META_OUTPUT_INPUT}" != "${META_OUTPUT}" ]]; then
  log_msg INFO "meta_output_input=${META_OUTPUT_INPUT}"
fi
log_msg INFO "meta_output=${META_OUTPUT:-<none>}"
log_msg INFO "target_profile_seed=${TARGET_PROFILE_SEED:-<none>}"
log_msg INFO "target_source_root=${TARGET_SOURCE_ROOT:-<none>}"
log_msg INFO "build_log=${BUILD_LOG:-<none>}"
log_msg INFO "execution_mode=${EXECUTION_MODE}"
log_msg INFO "patch_apply_mode=${PATCH_APPLY_MODE}"
log_msg INFO "prompt=${PROMPT}"
log_msg INFO "schema=${SCHEMA}"
log_msg INFO "codex=$(command -v codex)"
log_msg INFO "codex_model=${CODEX_MODEL:-default}"
log_msg INFO "extra_args=${CODEX_EXTRA_ARGS:-<none>}"
log_msg INFO "proxy=${CODEX_PROXY_URL}"
log_file_state prompt "${PROMPT}"
log_file_state schema "${SCHEMA}"
log_file_state source_task_profile "${SOURCE_OUTPUT}/00_config/task_profile.yaml"
log_file_state source_meta_inputs "${SOURCE_OUTPUT}/07_meta_inputs/scenario_card.yaml"
if [[ -n "${META_OUTPUT}" ]]; then
  log_file_state meta_report "${META_OUTPUT}/meta_report.md"
fi
if [[ -n "${TARGET_PROFILE_SEED}" ]]; then
  log_file_state target_profile_seed "${TARGET_PROFILE_SEED}"
fi
if [[ -n "${TARGET_SOURCE_ROOT}" ]]; then
  log_file_state target_source_root "${TARGET_SOURCE_ROOT}"
fi
if [[ -n "${BUILD_LOG}" ]]; then
  log_file_state build_log "${BUILD_LOG}"
fi

rm -f "${PENDING_RESULT}"
START_EPOCH="$(date +%s)"
if [[ "${DETERMINISTIC_PORTING_EXECUTION_ASSISTANT:-0}" == "1" ]]; then
  log_msg INFO "${STAGE}: using deterministic generate_porting_execution_assistant.py"
  DET_ARGS=(
    --workspace "${WORKSPACE_ROOT}"
    --out "${OUT_DIR}"
    --artifact-root "${ARTIFACT_DIR}"
    --source-output "${SOURCE_OUTPUT}"
    --stage-result "${PENDING_RESULT}"
    --execution-mode "${EXECUTION_MODE}"
    --patch-apply-mode "${PATCH_APPLY_MODE}"
  )
  if [[ -n "${META_OUTPUT}" ]]; then
    DET_ARGS+=(--meta-output "${META_OUTPUT}")
  fi
  if [[ -n "${TARGET_PROFILE_SEED}" ]]; then
    DET_ARGS+=(--target-profile "${TARGET_PROFILE_SEED}")
  fi
  if [[ -n "${TARGET_SOURCE_ROOT}" ]]; then
    DET_ARGS+=(--target-source-root "${TARGET_SOURCE_ROOT}")
  fi
  if [[ -n "${BUILD_LOG}" ]]; then
    DET_ARGS+=(--build-log "${BUILD_LOG}")
  fi
  if python3 "${TOOLS_DIR}/generate_porting_execution_assistant.py" "${DET_ARGS[@]}" > "${LOG}" 2>&1; then
    END_EPOCH="$(date +%s)"
    log_msg INFO "${STAGE}: deterministic generation completed in $((END_EPOCH - START_EPOCH))s"
  else
    RC=$?
    END_EPOCH="$(date +%s)"
    log_msg ERROR "${STAGE}: deterministic generation failed with exit_code=${RC} after $((END_EPOCH - START_EPOCH))s"
    log_file_state ndjson_log "${LOG}"
    log_file_state pending_result "${PENDING_RESULT}"
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
  log_file_state ndjson_log "${LOG}"
  log_file_state pending_result "${PENDING_RESULT}"
  tail -n 120 "${LOG}" | tee -a "${PIPELINE_LOG}" || true
  archive_failed_attempt
  exit "${RC}"
fi

log_file_state ndjson_log "${LOG}"
log_file_state pending_result "${PENDING_RESULT}"
log_msg INFO "${STAGE}: validation_log=${VALIDATION_LOG}"
if python3 "${TOOLS_DIR}/validate_porting_execution_assistant.py" \
  --workspace "${WORKSPACE_ROOT}" \
  --out "${OUT_DIR}" \
  --stage-result "${PENDING_RESULT}" \
  --artifact-root "${ARTIFACT_DIR}" 2>&1 | tee "${VALIDATION_LOG}"; then
  mv "${PENDING_RESULT}" "${RESULT}"
  publish_success_attempt
  log_file_state promoted_result "${RESULT}"
  log_msg INFO "${STAGE}: validation passed"
else
  RC=$?
  log_msg ERROR "${STAGE}: validation failed with exit_code=${RC}"
  tail -n 120 "${VALIDATION_LOG}" | tee -a "${PIPELINE_LOG}" || true
  archive_failed_attempt
  exit "${RC}"
fi

echo "Porting execution assistant finished. Output: ${ARTIFACT_DIR}"
echo "移植执行辅助已完成。输出目录：${ARTIFACT_DIR}"
