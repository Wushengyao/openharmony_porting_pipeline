# Stage 11: OpenHarmony Version-Upgrade Porting

This is an isolated Codex session. Do not assume previous chat context.

This optional stage handles the four-tree upgrade case:

- `old_original`: old clean OpenHarmony/vendor baseline before target porting.
- `old_ported`: old version after the board/SoC/product port was completed.
- `new_original`: new clean OpenHarmony/vendor baseline before target porting.
- `new_workspace`: new version workspace that will receive the port.

`old_original` must be the exact frozen baseline used before the old port
started. Do not substitute a moving latest OpenHarmony release branch. If the
directory is unavailable, prefer a locked manifest from `old_ported`, such as
`.repo/manifests/tag/*.xml`, and generate a baseline reconstruction plan before
claiming a complete four-tree comparison.

The stage is plan-only. It must not edit source files, apply patches, fetch
external assets, install packages, or claim boot/runtime/test success.

At the end, return JSON conforming to
`schemas/version_upgrade_porting.schema.json`.

## Environment

The runner may export:

- `VERSION_UPGRADE_OLD_ORIGINAL`
- `VERSION_UPGRADE_OLD_PORTED`
- `VERSION_UPGRADE_OLD_BASELINE_MANIFEST`, optional locked manifest that
  reconstructs `old_original` from `old_ported`
- `VERSION_UPGRADE_NEW_ORIGINAL`
- `VERSION_UPGRADE_NEW_WORKSPACE`
- `VERSION_UPGRADE_OUT_DIR`, default `porting_knowledge_output/`
- `VERSION_UPGRADE_ARTIFACT_DIR`, default
  `porting_knowledge_output/09_version_upgrade/`
- `VERSION_UPGRADE_TARGET_PROFILE_SEED`, optional target profile YAML
- `VERSION_UPGRADE_BUILD_LOG`, optional new-workspace build log for triage

If an environment variable is unset, record `unknown` and add an
`uncertainty_ledger` item. Do not invent missing paths, board names, product
names, architecture, or validation results.

## Preferred Deterministic Seed

If the runner already produced files under
`VERSION_UPGRADE_ARTIFACT_DIR`, read them first:

- `four_tree_profile.yaml`
- `old_original_baseline.yaml`
- `old_original_baseline.md`
- `old_porting_delta.csv` and `.md`
- `upstream_upgrade_delta.csv` and `.md`
- `new_workspace_delta.csv` and `.md`
- `four_tree_conflict_matrix.yaml` and `.md`
- `migration_requirement_index.yaml` and `.md`
- `upgrade_porting_work_order.yaml` and `.md`
- `upgrade_patch_plan.yaml` and `.md`
- `external_dependency_followup.yaml` and `.md`
- `build_acceptance.yaml` and `.md`
- `uncertainty_ledger.yaml` and `.md`
- `upgrade_porting_summary.yaml` and `.md`

Treat those files as evidence, not as authorization to modify the workspace.
You may refine the human Markdown and machine YAML, but preserve deterministic
counts unless you have direct evidence for a correction.

## Required Output Files

Create or update all files under `VERSION_UPGRADE_ARTIFACT_DIR`:

- `four_tree_profile.yaml`
- `old_original_baseline.yaml`
- `old_original_baseline.md`
- `old_porting_delta.csv`
- `old_porting_delta.md`
- `upstream_upgrade_delta.csv`
- `upstream_upgrade_delta.md`
- `new_workspace_delta.csv`
- `new_workspace_delta.md`
- `four_tree_conflict_matrix.yaml`
- `four_tree_conflict_matrix.md`
- `migration_requirement_index.yaml`
- `migration_requirement_index.md`
- `upgrade_porting_work_order.yaml`
- `upgrade_porting_work_order.md`
- `upgrade_patch_plan.yaml`
- `upgrade_patch_plan.md`
- `external_dependency_followup.yaml`
- `external_dependency_followup.md`
- `build_acceptance.yaml`
- `build_acceptance.md`
- `uncertainty_ledger.yaml`
- `uncertainty_ledger.md`
- `upgrade_porting_summary.yaml`
- `upgrade_porting_summary.md`

Every YAML file must include:

```yaml
schema_version: 1
artifact_type: <matching artifact name>
generated_at: <ISO-like local timestamp>
```

Every recommendation/action/gap/requirement record must include non-empty
`evidence_refs`. Use these prefixes:

- `old_porting_delta:`
- `upstream_upgrade_delta:`
- `new_workspace_delta:`
- `four_tree_conflict_matrix:`
- `target_profile:`
- `build_log:`
- `workspace:`
- `unknown:`

Use `unknown:` only in `uncertainty_ledger`.

## Four-Tree Reasoning Rules

1. `old_original -> old_ported` is the old target-porting delta. Extract the
   engineering intent from this delta; do not blindly replay text patches.
2. `old_original` is valid only when it is the exact pre-port frozen baseline.
   A later-updated official 6.0 branch, vendor release branch, or community
   branch is not a valid substitute because it mixes upstream churn into the
   old-porting delta.
3. If `old_original` is missing, use a locked manifest from `old_ported` to
   identify `manifest_revision..HEAD` deltas and emit
   `old_original_baseline`. Mark the stage `partial` until the exact baseline is
   reconstructed and used for the full `old_original -> new_original` delta.
4. `old_original -> new_original` is upstream OpenHarmony/vendor version churn.
   Use it to identify paths, modules, APIs, build rules, or component metadata
   that changed independently of the target port.
5. `new_original -> new_workspace` is current migration progress or local drift.
   Do not overwrite it without review; classify it as already-in-progress
   evidence.
6. For each old-porting item, classify the new-version migration decision:
   `direct_review_candidate`, `merge_required`, `manual_retarget_required`,
   `already_in_progress_review`,
   `route_to_external_dependency_followup`, or `unknown`.
7. Keep product/component/feature declarations visible where possible. Do not
   remove a feature merely to get a build to pass.
8. Route BSP, firmware, bootloader, kernel modules, closed drivers, signing
   tools, prebuilts, HAPs, and proprietary shared libraries to
   `external_dependency_followup`. They are dependency evidence, not source
   fixes.
9. Compile-only fake interfaces may be planned only as explicit build-triage
   bridges. They must be marked as fake, runtime-nonfunctional, and replaceable
   by provenance-checked real dependencies.
10. Build acceptance is compile-flow evidence only. Never infer boot, runtime,
   driver runtime, app, CTS, or test pass from a build pass.
11. Missing evidence belongs in `uncertainty_ledger`, not in confident action
   plans.
12. Preserve original pipeline behavior: this stage is optional and must not
    change `run_pipeline.sh` default stage order or Stage 10 execution-assistant
    semantics.

## Phase Model

Use these phases in work orders and requirements:

- `L0_target_identity`: product name, productdefine JSON, inheritance, vendor
  identity.
- `L1_base_binding`: vendor product config, board config, SoC config,
  `ohos.build`, `BUILD.gn`, `bundle.json`, component/feature registries.
- `L2_build_triage`: build-system, toolchain, architecture, ArkCompiler, ArkUI,
  WebView, FFRT, Rust, NDK, graphic, multimedia, communication, request,
  resourceschedule, and third-party source/build compatibility.
- `L3_runtime_hdf_config`: HDF, `.hcs`, runtime parameters, audio/display/camera
  configs, service wiring.
- `L4_feature_driver_source`: target-specific driver or feature source closures.
- `L5_external_dependency_closure`: BSP, kernel source, firmware, bootloader,
  prebuilts, closed drivers, signing/packaging tools, and provenance inventory.

## Artifact Intent

- `four_tree_profile`: root paths, scan scope, counts, and guardrails.
- `old_original_baseline`: exact baseline source, locked manifest, and
  reconstruction command or proof that an old-original directory was supplied.
- `old_porting_delta`: old target-porting changes.
- `upstream_upgrade_delta`: upstream version changes.
- `new_workspace_delta`: current target workspace drift from the new baseline.
- `four_tree_conflict_matrix`: per-path migration decision and risk.
- `migration_requirement_index`: complete migration requirements derived from
  the matrix.
- `upgrade_porting_work_order`: manually reviewable execution batches.
- `upgrade_patch_plan`: plan-only patch candidates; no diff hunks.
- `external_dependency_followup`: dependency requests and metadata requirements.
- `build_acceptance`: build-only commands using existing workspace scripts.
- `uncertainty_ledger`: unknowns, impact, and next evidence checks.
- `upgrade_porting_summary`: compact handoff summary.

## Final JSON

Return only JSON:

```json
{
  "stage": "11_version_upgrade_porting",
  "status": "passed",
  "summary": "four-tree version-upgrade porting evidence generated",
  "execution_mode": "plan-only",
  "artifact_root": "porting_knowledge_output/09_version_upgrade",
  "baseline_mode": "unknown",
  "old_baseline_manifest": "unknown",
  "input_roots": {
    "old_original": "unknown",
    "old_ported": "unknown",
    "new_original": "unknown",
    "new_workspace": "unknown"
  },
  "input_files_read": [],
  "output_files_written": [],
  "blocking_issues": [],
  "non_blocking_issues": [],
  "next_stage_inputs": [],
  "old_porting_delta_count": 0,
  "upstream_upgrade_delta_count": 0,
  "new_workspace_delta_count": 0,
  "conflict_item_count": 0,
  "external_dependency_followup_count": 0,
  "uncertainty_count": 0
}
```
