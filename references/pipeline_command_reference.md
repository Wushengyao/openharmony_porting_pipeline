# Pipeline Command Reference

Use this reference when running the OpenHarmony porting knowledge pipeline,
dispatching subagent work, applying reviewed base patches, or validating
cross-scenario outputs. Keep `SKILL.md` as the navigation layer and put command
details here.

## Contents

- [Subagent Contracts](#subagent-contracts)
- [Pipeline Runs](#pipeline-runs)
- [Execution Assistant And Base Patch](#execution-assistant-and-base-patch)
- [Four-Tree Version Upgrade](#four-tree-version-upgrade)
- [Cross-Scenario Aggregation](#cross-scenario-aggregation)
- [Validation](#validation)

## Subagent Contracts

Read the coordination contract before creating or dispatching tasks:

```bash
cat /home/ve/.codex/skills/openharmony_porting_pipeline/docs/agent_architecture.md
cat /home/ve/.codex/skills/openharmony_porting_pipeline/AGENTS.md
```

Use these schemas for task, evidence, and acceptance files:

```text
schemas/agent_task.schema.json
schemas/evidence_pack.schema.json
schemas/acceptance_state.schema.json
```

The main agent keeps decomposition, evidence judgment, writer-lock decisions,
patch merge, and final acceptance. Subagents default to read-only evidence
collection unless the main agent explicitly grants a scoped writer role.

## Pipeline Runs

Run the full pipeline on an OpenHarmony workspace:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_pipeline.sh /path/to/ohos
```

Run in human-collaboration mode:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_pipeline.sh --mode collab /path/to/ohos
```

Run one stage:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_stage.sh /path/to/ohos 03_statistics_qc
```

Use `porting_knowledge_output/` as the default output root unless the user
specifies another directory.

## Execution Assistant And Base Patch

Run the plan-only execution assistant after the evidence pipeline:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_porting_execution_assistant.sh \
  --source-output /path/to/ohos/porting_knowledge_output \
  --meta-output /path/to/openharmony_porting_meta_output_or_zip \
  --target-profile /path/to/target_profile_seed.yaml \
  --target-source-root /path/to/reference_target_ohos \
  /path/to/ohos
```

Stage, apply, and optionally compile-test a reviewed L0/L1 base patch:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/apply_porting_base_patch.py \
  --workspace /path/to/ohos \
  --target-source-root /path/to/reference_target_ohos \
  --target-profile /path/to/target_profile_seed.yaml \
  --out /path/to/ohos/porting_knowledge_output/base_patch_apply \
  --apply \
  --attempt-build
```

Continue after real vendor/BSP dependencies arrive:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/apply_porting_base_patch.py \
  --workspace /path/to/ohos \
  --target-source-root /path/to/reference_target_ohos \
  --target-profile /path/to/target_profile_seed.yaml \
  --real-dependency-inventory /path/to/real_dependency_inventory.yaml \
  --out /path/to/ohos/porting_knowledge_output/base_patch_apply_real_deps \
  --apply \
  --attempt-build
```

The real dependency inventory is a YAML mapping with a `real_dependencies`
list. Each entry should name the workspace `path`, provider, source/version,
license or authorization reference, sha256 when available, and
`replacement_for_fake` when it replaces a fake marker such as
`kernel/linux/<board-kernel>/.openharmony_porting_fake_kernel_source`.

Inventory-backed dependencies are preserved and excluded from fake-interface
debt. Missing, fake-marked, hash-mismatched, or ABI-mismatched entries block
the run. Use `--prefer-existing-real-dependencies` only after existing fake
placeholders have been reviewed or removed.

## Four-Tree Version Upgrade

Run four-tree analysis when an old completed port must be migrated to a newer
unported OpenHarmony baseline:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_version_upgrade_porting.sh \
  --old-original /path/to/old_clean_ohos \
  --old-ported /path/to/old_ported_ohos \
  --new-original /path/to/new_clean_ohos \
  --new-workspace /path/to/new_unported_ohos
```

The four inputs mean:

- `old-original`: old clean baseline before the board/SoC/product port.
- `old-ported`: old version after that port was completed.
- `new-original`: new clean baseline before the port.
- `new-workspace`: new version workspace that will receive the migrated port.

`old-original` must be the exact frozen pre-port baseline. Do not substitute a
moving latest official/vendor/community branch for the same OpenHarmony version.
If the directory is missing, point the runner at a locked manifest from
`old-ported`, or let it auto-detect `.repo/manifests/tag/*.xml`:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_version_upgrade_porting.sh \
  --old-ported /path/to/old_ported_ohos \
  --old-baseline-manifest /path/to/old_ported_ohos/.repo/manifests/tag/manifest_tag_xxx.xml \
  --new-original /path/to/new_clean_ohos \
  --new-workspace /path/to/new_unported_ohos
```

Manifest-only mode is partial. It extracts old-porting deltas from
`manifest_revision..HEAD` and emits `old_original_baseline.*` with the
reconstruction command. Reconstruct and supply the exact `old-original` tree
before claiming complete upstream-churn analysis.

For OH6.x RISC-V work that must progress from four-tree analysis to build,
flash/recovery, UI, and test-team `rc0`, also read:

```bash
cat /home/ve/.codex/skills/openharmony_porting_pipeline/docs/oh6_riscv_version_upgrade_rc0.md
```

## Cross-Scenario Aggregation

Aggregate multiple scenario outputs:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_cross_scenario_aggregator.sh \
  --input scenario_outputs/t113/porting_knowledge_output \
  --input scenario_outputs/ruyios/porting_knowledge_output \
  --out openharmony_porting_meta_output
```

Validate an existing cross-scenario output:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/validate_meta_output.py --out openharmony_porting_meta_output
```

Cross-scenario aggregation emits `meta_skill_pack/` with installable `SKILL.md`
drafts plus `_validate_meta_output.log` for the validation transcript.

## Validation

For pipeline script changes, run the smallest relevant checks:

```bash
bash -n tools/run_pipeline.sh
bash -n tools/run_stage.sh
bash -n tools/run_porting_execution_assistant.sh
python3 -m py_compile tools/apply_porting_base_patch.py
python3 -m py_compile tools/compare_four_tree_upgrade.py
python3 -m py_compile tools/validate_porting_execution_assistant.py
python3 -m json.tool schemas/porting_execution_assistant.schema.json >/dev/null
python3 -m json.tool schemas/version_upgrade_porting.schema.json >/dev/null
```

For skill structural changes, also run:

```bash
python3 /home/ve/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /home/ve/.codex/skills/openharmony_porting_pipeline
```
