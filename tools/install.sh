#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: install.sh <openharmony_workspace>" >&2
  exit 2
fi

WORKSPACE="$(cd "$1" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

mkdir -p "${WORKSPACE}/.agents/skills"
mkdir -p "${WORKSPACE}/.codex/agents"
mkdir -p "${WORKSPACE}/.codex/openharmony_porting_pipeline"

rsync -a "${PKG_ROOT}/.agents/skills/" "${WORKSPACE}/.agents/skills/"
rsync -a "${PKG_ROOT}/.codex/agents/" "${WORKSPACE}/.codex/agents/"
rsync -a "${PKG_ROOT}/.codex/openharmony_porting_pipeline/" "${WORKSPACE}/.codex/openharmony_porting_pipeline/"

if [[ ! -f "${WORKSPACE}/.codex/config.toml" ]]; then
  cp "${PKG_ROOT}/.codex/config.toml" "${WORKSPACE}/.codex/config.toml"
  echo "Created ${WORKSPACE}/.codex/config.toml"
else
  cp "${PKG_ROOT}/.codex/config.toml" "${WORKSPACE}/.codex/openharmony_porting_config.template.toml"
  echo "Existing .codex/config.toml kept. Template copied to .codex/openharmony_porting_config.template.toml"
fi

cat <<EOF
Installed OpenHarmony porting multi-agent skills into:
  ${WORKSPACE}

Run:
  cd ${WORKSPACE}
  bash .codex/openharmony_porting_pipeline/tools/run_pipeline.sh "\$PWD"

Optional model override:
  CODEX_MODEL="gpt-5.5" bash .codex/openharmony_porting_pipeline/tools/run_pipeline.sh "\$PWD"
EOF
