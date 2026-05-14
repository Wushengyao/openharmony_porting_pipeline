#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROMPT="${REPO_ROOT}/prompts/09_cross_scenario_aggregator.md"
SCHEMA="${REPO_ROOT}/schemas/stage_result.schema.json"
LLM_REFINE=0
ARGS=()
OUT_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --llm-refine)
      LLM_REFINE=1
      shift
      ;;
    --out)
      OUT_DIR="${2:-}"
      ARGS+=(--out "${OUT_DIR}")
      shift 2
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

if [[ -z "${OUT_DIR}" ]]; then
  echo "--out is required" >&2
  exit 2
fi

bash "${SCRIPT_DIR}/run_cross_scenario_aggregator.sh" "${ARGS[@]}"

if [[ "${LLM_REFINE}" != "1" ]]; then
  exit 0
fi

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found; deterministic meta output was generated but LLM refinement was skipped" >&2
  exit 127
fi

LOG_DIR="${OUT_DIR}/_codex_logs"
mkdir -p "${LOG_DIR}"
RUN_ID="$(date '+%Y%m%d_%H%M%S')"
RESULT="${LOG_DIR}/09_cross_scenario_refine.${RUN_ID}.json"
LOG="${LOG_DIR}/09_cross_scenario_refine.${RUN_ID}.ndjson"

CODEX_BASE_ARGS=(--cd "$(cd "${OUT_DIR}" && pwd)" --sandbox workspace-write --skip-git-repo-check --ephemeral --json)
if [[ -n "${CODEX_MODEL:-}" ]]; then
  CODEX_BASE_ARGS+=(--model "${CODEX_MODEL}")
fi
# shellcheck disable=SC2206
EXTRA_ARGS=(${CODEX_EXTRA_ARGS:-})

CROSS_SCENARIO_META_OUTPUT="${OUT_DIR}" \
codex exec \
  "${CODEX_BASE_ARGS[@]}" \
  "${EXTRA_ARGS[@]}" \
  --output-last-message "${RESULT}" \
  --output-schema "${SCHEMA}" \
  - < "${PROMPT}" > "${LOG}" 2>&1

python3 "${SCRIPT_DIR}/validate_meta_output.py" --out "${OUT_DIR}"
echo "Cross-scenario aggregation and LLM refinement finished. Output: ${OUT_DIR}"
