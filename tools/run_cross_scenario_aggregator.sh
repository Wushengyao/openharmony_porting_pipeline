#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUTS=()
INPUT_ROOT=""
OUT_DIR=""
LLM_REFINE=0
CODEX_MODEL_VALUE="${CODEX_MODEL:-}"
REDACT_LOCAL_PATHS=0

usage() {
  cat >&2 <<'EOF'
用法：
  run_cross_scenario_aggregator.sh --input <porting_knowledge_output|07_meta_inputs> [--input <...>] --out <openharmony_porting_meta_output> [--llm-refine]
  run_cross_scenario_aggregator.sh --input-root <scenario_outputs_root> --out <openharmony_porting_meta_output> [--llm-refine]

说明：
  --input 可以指向 porting_knowledge_output 或其中的 07_meta_inputs。
  --input-root 会自动查找 */porting_knowledge_output/07_meta_inputs/scenario_card.yaml。
  --llm-refine 会在确定性聚合之后调用 Codex，基于 compact meta 输入精修方法论文本。
  --redact-local-paths 会在 meta registry/result 中隐藏绝对本地路径，仅保留 label/relative 字段。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --input)
      INPUTS+=("${2:-}")
      shift 2
      ;;
    --input-root)
      INPUT_ROOT="${2:-}"
      shift 2
      ;;
    --out)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --llm-refine)
      LLM_REFINE=1
      shift
      ;;
    --redact-local-paths)
      REDACT_LOCAL_PATHS=1
      shift
      ;;
    --model)
      CODEX_MODEL_VALUE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${OUT_DIR}" ]]; then
  echo "--out 必填" >&2
  usage
  exit 2
fi
if [[ ${#INPUTS[@]} -eq 0 && -z "${INPUT_ROOT}" ]]; then
  echo "至少提供一个 --input 或 --input-root" >&2
  usage
  exit 2
fi

ARGS=()
for input in "${INPUTS[@]}"; do
  if [[ -z "${input}" ]]; then
    echo "--input 不能为空" >&2
    exit 2
  fi
  ARGS+=(--input "${input}")
done
if [[ -n "${INPUT_ROOT}" ]]; then
  ARGS+=(--input-root "${INPUT_ROOT}")
fi
if [[ "${REDACT_LOCAL_PATHS}" == "1" ]]; then
  ARGS+=(--redact-local-paths)
fi
ARGS+=(--out "${OUT_DIR}")

echo "[INFO] aggregating cross-scenario meta output: ${OUT_DIR}" >&2
python3 "${SCRIPT_DIR}/aggregate_cross_scenario.py" "${ARGS[@]}"
if [[ "${LLM_REFINE}" == "1" ]]; then
  CODEX_LOG_DIR="${OUT_DIR}/_codex_logs"
  mkdir -p "${CODEX_LOG_DIR}"
  if ! command -v codex >/dev/null 2>&1; then
    echo "[WARN] --llm-refine requested but codex is not in PATH; skip LLM refinement" >&2
  else
    PROMPT="${SCRIPT_DIR}/../prompts/09_cross_scenario_aggregator.md"
    SCHEMA="${SCRIPT_DIR}/../schemas/stage_result.schema.json"
    RESULT="${OUT_DIR}/_llm_refine_result.json"
    LOG="${OUT_DIR}/_llm_refine.ndjson"
    mkdir -p "${OUT_DIR}"
    rm -f "${CODEX_LOG_DIR}/09_cross_scenario_refine.skipped.json"
    BACKUP_DIR="$(mktemp -d "${OUT_DIR}.pre_llm.XXXXXX")"
    cp -a "${OUT_DIR}/." "${BACKUP_DIR}/"
    BASE_ARGS=(--cd "$(pwd)" --sandbox workspace-write --skip-git-repo-check --ephemeral --json)
    if [[ -n "${CODEX_MODEL_VALUE}" ]]; then
      BASE_ARGS+=(--model "${CODEX_MODEL_VALUE}")
    fi
    echo "[INFO] running Codex LLM refinement for cross-scenario methodology" >&2
    set +e
    CROSS_SCENARIO_META_OUTPUT="${OUT_DIR}" \
    codex exec \
      "${BASE_ARGS[@]}" \
      --output-last-message "${RESULT}" \
      --output-schema "${SCHEMA}" \
      - < "${PROMPT}" > "${LOG}" 2>&1
    CODEX_STATUS=$?
    set -e
    if [[ "${CODEX_STATUS}" -ne 0 ]]; then
      FAILED_LOG="${BACKUP_DIR}/_llm_refine.failed.ndjson"
      [[ -f "${LOG}" ]] && cp "${LOG}" "${FAILED_LOG}"
      if [[ ! -f "${FAILED_LOG}" ]]; then
        printf '{"type":"error","message":"Codex LLM refinement failed before writing a log."}\n' > "${FAILED_LOG}"
      fi
      rm -rf "${OUT_DIR}"
      mkdir -p "${OUT_DIR}"
      cp -a "${BACKUP_DIR}/." "${OUT_DIR}/"
      mkdir -p "${OUT_DIR}/_codex_logs"
      if [[ -f "${FAILED_LOG}" ]]; then
        cp "${FAILED_LOG}" "${OUT_DIR}/_llm_refine.ndjson"
        cp "${FAILED_LOG}" "${OUT_DIR}/_codex_logs/09_cross_scenario_refine.ndjson"
        cp "${FAILED_LOG}" "${OUT_DIR}/_codex_logs/09_cross_scenario_refine.failed.ndjson"
      fi
      python3 - "${OUT_DIR}/_llm_refine_result.json" <<'PY'
import json
import sys
from datetime import datetime

path = sys.argv[1]
result = {
    "stage": "09_cross_scenario_refine",
    "status": "partial",
    "summary": "LLM refinement was requested but failed; deterministic cross-scenario output was restored.",
    "input_files_read": [],
    "output_files_written": ["_llm_refine.ndjson", "_codex_logs/09_cross_scenario_refine.failed.ndjson"],
    "blocking_issues": [],
    "non_blocking_issues": ["LLM refinement failed; inspect _codex_logs/09_cross_scenario_refine.failed.ndjson."],
    "next_stage_inputs": ["openharmony_porting_meta_output"],
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
}
with open(path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
    f.write("\n")
PY
      echo "[WARN] LLM refinement failed; deterministic meta output was restored. See ${OUT_DIR}/_codex_logs/09_cross_scenario_refine.failed.ndjson" >&2
    else
      cp "${LOG}" "${CODEX_LOG_DIR}/09_cross_scenario_refine.ndjson"
      if [[ -f "${BACKUP_DIR}/cross_scenario_result.json" ]]; then
        cp "${BACKUP_DIR}/cross_scenario_result.json" "${OUT_DIR}/cross_scenario_result.json"
      fi
      python3 "${SCRIPT_DIR}/normalize_meta_output_contract.py" --out "${OUT_DIR}"
    fi
    rm -rf "${BACKUP_DIR}"
  fi
fi
echo "[INFO] validating meta output: ${OUT_DIR}" >&2
python3 "${SCRIPT_DIR}/validate_meta_output.py" --out "${OUT_DIR}" 2>&1 | tee "${OUT_DIR}/_validate_meta_output.log"
echo "Cross-scenario aggregation finished. Output: ${OUT_DIR}"
