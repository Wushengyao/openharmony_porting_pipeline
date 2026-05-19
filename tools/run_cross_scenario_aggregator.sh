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
  if ! command -v codex >/dev/null 2>&1; then
    echo "[WARN] --llm-refine requested but codex is not in PATH; skip LLM refinement" >&2
  else
    PROMPT="${SCRIPT_DIR}/../prompts/09_cross_scenario_aggregator.md"
    SCHEMA="${SCRIPT_DIR}/../schemas/stage_result.schema.json"
    RESULT="${OUT_DIR}/_llm_refine_result.json"
    LOG="${OUT_DIR}/_llm_refine.ndjson"
    mkdir -p "${OUT_DIR}"
    BASE_ARGS=(--cd "$(pwd)" --sandbox workspace-write --skip-git-repo-check --ephemeral --json)
    if [[ -n "${CODEX_MODEL_VALUE}" ]]; then
      BASE_ARGS+=(--model "${CODEX_MODEL_VALUE}")
    fi
    echo "[INFO] running Codex LLM refinement for cross-scenario methodology" >&2
    CROSS_SCENARIO_META_OUTPUT="${OUT_DIR}" \
    codex exec \
      "${BASE_ARGS[@]}" \
      --output-last-message "${RESULT}" \
      --output-schema "${SCHEMA}" \
      - < "${PROMPT}" > "${LOG}" 2>&1 || {
        echo "[WARN] LLM refinement failed; deterministic meta output is preserved. See ${LOG}" >&2
      }
    python3 "${SCRIPT_DIR}/normalize_meta_output_contract.py" --out "${OUT_DIR}"
  fi
fi
echo "[INFO] validating meta output: ${OUT_DIR}" >&2
python3 "${SCRIPT_DIR}/validate_meta_output.py" --out "${OUT_DIR}" 2>&1 | tee "${OUT_DIR}/_validate_meta_output.log"
echo "Cross-scenario aggregation finished. Output: ${OUT_DIR}"
