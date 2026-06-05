#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TOOLS_DIR="${PIPELINE_DIR}/tools"

OLD_ORIGINAL=""
OLD_PORTED=""
NEW_ORIGINAL=""
NEW_WORKSPACE=""
OLD_BASELINE_MANIFEST=""
AUTO_OLD_BASELINE_MANIFEST="1"
OUT_DIR=""
ARTIFACT_DIR=""
MAX_RECORDS="20000"
FOCUS_PATHS=()

usage() {
  cat >&2 <<'EOF'
Usage: run_version_upgrade_porting.sh --old-ported DIR --new-original DIR [options]

Options:
  --old-original DIR      Old clean OpenHarmony/vendor baseline before porting.
                          Prefer the exact frozen baseline, not a moving latest release branch.
  --old-ported DIR        Old version after the board/SoC port was completed.
  --new-original DIR      New clean OpenHarmony/vendor baseline before porting.
  --new-workspace DIR     New version workspace to be ported. Defaults to $PWD.
  --old-baseline-manifest FILE
                          Locked manifest from old-ported that reconstructs old-original.
                          If --old-original is absent, this can seed old-porting deltas.
  --no-auto-old-baseline-manifest
                          Do not auto-detect old-ported/.repo/manifests/tag/*.xml.
  --out DIR               Output root. Defaults to <new-workspace>/porting_knowledge_output.
  --artifact-root DIR     Four-tree artifact directory. Defaults to <out>/09_version_upgrade.
  --focus-path PATH       Limit scanning to a path relative to each root. May repeat.
  --max-records N         Maximum records per delta scan. Default: 20000.
  -h, --help              Show this help.

This P0 runner is plan-only. It writes evidence and work-order artifacts but
does not modify the new workspace, apply patches, fetch dependencies, or claim
boot/runtime/test success.

If --old-original is unavailable, the runner uses a locked old baseline manifest
from old_ported to generate a partial, evidence-bound baseline reconstruction
plan. Reconstruct that exact baseline before treating the run as a complete
four-tree comparison.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --old-original)
      OLD_ORIGINAL="${2:-}"
      shift 2
      ;;
    --old-ported)
      OLD_PORTED="${2:-}"
      shift 2
      ;;
    --old-baseline-manifest)
      OLD_BASELINE_MANIFEST="${2:-}"
      shift 2
      ;;
    --no-auto-old-baseline-manifest)
      AUTO_OLD_BASELINE_MANIFEST="0"
      shift
      ;;
    --new-original)
      NEW_ORIGINAL="${2:-}"
      shift 2
      ;;
    --new-workspace)
      NEW_WORKSPACE="${2:-}"
      shift 2
      ;;
    --out)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    --artifact-root)
      ARTIFACT_DIR="${2:-}"
      shift 2
      ;;
    --focus-path)
      FOCUS_PATHS+=("${2:-}")
      shift 2
      ;;
    --max-records)
      MAX_RECORDS="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${OLD_PORTED}" || -z "${NEW_ORIGINAL}" ]]; then
  echo "--old-ported and --new-original are required." >&2
  usage
  exit 2
fi

abs_dir() {
  local path="$1" label="$2"
  if [[ ! -d "${path}" ]]; then
    echo "${label} must be an existing directory: ${path}" >&2
    exit 2
  fi
  cd "${path}" && pwd
}

if [[ -n "${OLD_ORIGINAL}" ]]; then
  OLD_ORIGINAL="$(abs_dir "${OLD_ORIGINAL}" "--old-original")"
fi
OLD_PORTED="$(abs_dir "${OLD_PORTED}" "--old-ported")"
NEW_ORIGINAL="$(abs_dir "${NEW_ORIGINAL}" "--new-original")"
if [[ -n "${OLD_BASELINE_MANIFEST}" ]]; then
  if [[ ! -f "${OLD_BASELINE_MANIFEST}" ]]; then
    echo "--old-baseline-manifest must be an existing file: ${OLD_BASELINE_MANIFEST}" >&2
    exit 2
  fi
  OLD_BASELINE_MANIFEST="$(cd "$(dirname "${OLD_BASELINE_MANIFEST}")" && pwd)/$(basename "${OLD_BASELINE_MANIFEST}")"
fi
if [[ -z "${NEW_WORKSPACE}" ]]; then
  NEW_WORKSPACE="$PWD"
fi
NEW_WORKSPACE="$(abs_dir "${NEW_WORKSPACE}" "--new-workspace")"
if [[ -z "${OUT_DIR}" ]]; then
  OUT_DIR="${NEW_WORKSPACE}/porting_knowledge_output"
fi
mkdir -p "${OUT_DIR}"
OUT_DIR="$(cd "${OUT_DIR}" && pwd)"
if [[ -z "${ARTIFACT_DIR}" ]]; then
  ARTIFACT_DIR="${OUT_DIR}/09_version_upgrade"
fi
mkdir -p "${ARTIFACT_DIR}" "${OUT_DIR}/_stage_results" "${OUT_DIR}/_codex_stage_logs"
ARTIFACT_DIR="$(cd "${ARTIFACT_DIR}" && pwd)"

RUN_ID="$(date '+%Y%m%d_%H%M%S')"
STAGE="11_version_upgrade_porting"
PENDING_RESULT="${OUT_DIR}/_stage_results/${STAGE}.${RUN_ID}.pending.json"
RESULT="${OUT_DIR}/_stage_results/${STAGE}.json"
LOG="${OUT_DIR}/_codex_stage_logs/${STAGE}.${RUN_ID}.log"
VALIDATION_LOG="${OUT_DIR}/_codex_stage_logs/${STAGE}.${RUN_ID}.validation.log"

COMPARE_ARGS=(
  --old-ported "${OLD_PORTED}"
  --new-original "${NEW_ORIGINAL}"
  --new-workspace "${NEW_WORKSPACE}"
  --out "${OUT_DIR}"
  --artifact-root "${ARTIFACT_DIR}"
  --stage-result "${PENDING_RESULT}"
  --max-records "${MAX_RECORDS}"
)
if [[ -n "${OLD_ORIGINAL}" ]]; then
  COMPARE_ARGS+=(--old-original "${OLD_ORIGINAL}")
fi
if [[ -n "${OLD_BASELINE_MANIFEST}" ]]; then
  COMPARE_ARGS+=(--old-baseline-manifest "${OLD_BASELINE_MANIFEST}")
fi
if [[ "${AUTO_OLD_BASELINE_MANIFEST}" == "0" ]]; then
  COMPARE_ARGS+=(--no-auto-old-baseline-manifest)
fi
for focus_path in "${FOCUS_PATHS[@]}"; do
  COMPARE_ARGS+=(--focus-path "${focus_path}")
done

echo "[INFO] four-tree version-upgrade scan"
echo "[INFO] old_original=${OLD_ORIGINAL:-<not supplied>}"
echo "[INFO] old_ported=${OLD_PORTED}"
echo "[INFO] old_baseline_manifest=${OLD_BASELINE_MANIFEST:-<auto>}"
echo "[INFO] new_original=${NEW_ORIGINAL}"
echo "[INFO] new_workspace=${NEW_WORKSPACE}"
echo "[INFO] out=${OUT_DIR}"
echo "[INFO] artifact_root=${ARTIFACT_DIR}"

if python3 "${TOOLS_DIR}/compare_four_tree_upgrade.py" "${COMPARE_ARGS[@]}" > "${LOG}" 2>&1; then
  mv -f "${PENDING_RESULT}" "${RESULT}"
else
  rc=$?
  echo "[ERROR] four-tree comparison failed; see ${LOG}" >&2
  tail -n 120 "${LOG}" >&2 || true
  exit "${rc}"
fi

if python3 "${TOOLS_DIR}/validate_stage.py" \
  --workspace "${NEW_WORKSPACE}" \
  --out "${OUT_DIR}" \
  --stage "${STAGE}" \
  --stage-result "${RESULT}" > "${VALIDATION_LOG}" 2>&1; then
  cp -f "${LOG}" "${OUT_DIR}/_codex_stage_logs/${STAGE}.log"
  cp -f "${VALIDATION_LOG}" "${OUT_DIR}/_codex_stage_logs/${STAGE}.validation.log"
else
  rc=$?
  echo "[ERROR] validation failed; see ${VALIDATION_LOG}" >&2
  tail -n 120 "${VALIDATION_LOG}" >&2 || true
  exit "${rc}"
fi

echo "Version-upgrade porting evidence generated: ${ARTIFACT_DIR}"
