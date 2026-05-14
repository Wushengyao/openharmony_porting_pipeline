#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INPUTS=()
INPUT_ROOT=""
OUT_DIR=""

usage() {
  cat >&2 <<'EOF'
用法：
  run_cross_scenario_aggregator.sh --input <porting_knowledge_output> [--input <...>] --out <openharmony_porting_meta_output>
  run_cross_scenario_aggregator.sh --input-root <scenario_outputs_root> --out <openharmony_porting_meta_output>

说明：
  --input 可以指向 porting_knowledge_output 或其中的 07_meta_inputs。
  --input-root 会自动查找 */porting_knowledge_output/07_meta_inputs/scenario_card.yaml。
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
ARGS+=(--out "${OUT_DIR}")

echo "[INFO] aggregating cross-scenario meta output: ${OUT_DIR}" >&2
python3 "${SCRIPT_DIR}/aggregate_cross_scenario.py" "${ARGS[@]}"
echo "[INFO] validating meta output: ${OUT_DIR}" >&2
python3 "${SCRIPT_DIR}/validate_meta_output.py" --out "${OUT_DIR}"
echo "Cross-scenario aggregation finished. Output: ${OUT_DIR}"
