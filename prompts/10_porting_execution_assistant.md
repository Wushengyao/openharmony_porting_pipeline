# Stage 10: OpenHarmony Porting Execution Assistant

This is a fresh isolated Codex session. Do not assume previous chat context.
This stage extends the pipeline from meta-methodology into execution assistance.
It does not replace the single-scenario pipeline, cross-scenario aggregator, or
meta_skill_pack. It writes a plan-only execution package.

At the end, return JSON conforming to
`schemas/porting_execution_assistant.schema.json`.

## Environment

The runner exports:

- `PORTING_EXECUTION_MODE`: P0 must be `plan-only`.
- `PORTING_EXECUTION_PATCH_APPLY_MODE`: P0 is `none` or `plan-only`.
- `PORTING_EXECUTION_OUT_DIR`: default `porting_knowledge_output/`.
- `PORTING_EXECUTION_ARTIFACT_DIR`: default
  `porting_knowledge_output/08_execution_assistant/`.
- `PORTING_EXECUTION_SOURCE_OUTPUT`: existing single-scenario pipeline output.
- `PORTING_EXECUTION_META_OUTPUT`: optional normalized cross-scenario meta
  output directory; the runner may derive it from a user-supplied `.zip`.
- `PORTING_EXECUTION_TARGET_PROFILE_SEED`: optional user-provided target profile
  seed YAML.
- `PORTING_EXECUTION_TARGET_SOURCE_ROOT`: optional read-only reference target
  source tree. Use it only for bounded product/board/SoC evidence extraction.
- `PORTING_EXECUTION_BUILD_LOG`: optional existing build log for triage.

If an environment variable is unset, use the default path above or write
`unknown`; do not invent missing facts.

## Required Output Files

Create all files under `PORTING_EXECUTION_ARTIFACT_DIR`:

- `target_profile.yaml`
- `meta_knowledge_digest.yaml`
- `meta_knowledge_digest.md`
- `target_source_evidence.yaml`
- `target_source_evidence.md`
- `source_import_plan.yaml`
- `source_import_plan.md`
- `porting_work_order.yaml`
- `porting_work_order.md`
- `implementation_readiness.yaml`
- `implementation_readiness.md`
- `source_file_blueprint.yaml`
- `source_file_blueprint.md`
- `source_candidate_manifest.yaml`
- `source_candidate_manifest.md`
- `source_tree_survey.yaml`
- `source_tree_survey.md`
- `gap_analysis.yaml`
- `gap_analysis.md`
- `porting_plan.yaml`
- `porting_plan.md`
- `patch_plan.yaml`
- `patch_plan.md`
- `build_acceptance.yaml`
- `build_acceptance.md`
- `external_dependency_followup.yaml`
- `external_dependency_followup.md`
- `target_dependency_inventory.yaml`
- `target_dependency_inventory.md`
- `porting_completion_summary.md`
- `uncertainty_ledger.yaml`
- `uncertainty_ledger.md`

Use YAML for machine-readable artifacts and Markdown for the human execution
brief. Each YAML file must include:

```yaml
schema_version: 1
artifact_type: <matching artifact name>
generated_at: <ISO-like local timestamp>
```

Each recommendation/action/command/patch/gap/requirement record must include
non-empty `evidence_refs`. Use only these evidence reference prefixes:

- `user_requirement:`
- `source_tree:`
- `source_file:`
- `task_profile:`
- `operator_context:`
- `raw_record:`
- `dirty_record:`
- `binary_asset:`
- `case:`
- `meta_method:`
- `method_fragment:`
- `pattern:`
- `log:`
- `build_log:`
- `workspace:`
- `unknown:`

Use `unknown:` only for `uncertainty_ledger` items. Other artifacts must cite at
least one user requirement, source-tree/source-file record, meta method, case, or
log evidence reference.

## Allowed Inputs

Prefer compact, already-produced pipeline outputs:

- `00_config/task_profile.yaml`
- `00_config/operator_context.*`
- `01_raw_records/repo_list.csv`
- `01_raw_records/repo_status.raw.txt`
- `01_raw_records/file_change_records.jsonl`
- `01_raw_records/dirty_file_records.jsonl`
- `01_raw_records/binary_asset_records.csv`
- `02_statistics/statistics_summary.json`
- `03_semantic_analysis/risk_items.md`
- `03_semantic_analysis/workaround_items.md`
- `04_knowledge_base/cases/*.md`
- `04_knowledge_base/binary_asset_index.md`
- `04_knowledge_base/binary_risk_report.md`
- `05_skill_output/generated_skill.md`
- `06_audit/final_audit_report.md`
- `07_meta_inputs/*.yaml`
- `07_meta_inputs/*.jsonl`

If `PORTING_EXECUTION_META_OUTPUT` exists, read compact methodology and selector
inputs only:

- `02_patterns/meta_methods.jsonl`
- `02_patterns/conditional_methods.jsonl`
- `02_patterns/method_fragments.jsonl`
- `02_patterns/anti_patterns.jsonl`
- `01_normalized_cases/cases.jsonl`
- `01_normalized_cases/cases_by_subsystem/*.jsonl`
- `03_methodology/*.md`
- `04_global_kb/problem_taxonomy.yaml`
- `04_global_kb/risk_taxonomy.yaml`
- `meta_skill_pack/references/conditional_method_index.md`
- `meta_skill_pack/examples/case_selector_examples.yaml`
- `meta_report.md`

If `PORTING_EXECUTION_TARGET_SOURCE_ROOT` exists, read it as a reference source
tree only. Bound the scan to target-relevant paths derived from the target
profile, such as `vendor/<vendor>/<product>`,
`device/board/<vendor>/<board>`, `device/soc/<soc_vendor>/<soc>`, and
`productdefine/common/products/<product>.json`. Do not bulk-mine unrelated
products, do not copy files, and do not present a reference file as already
implemented in the current workspace.

Survey source tree paths needed to identify existing OpenHarmony build entry
points and target-product structure. Prefer bounded reads such as `find`,
`rg --files`, and small file excerpts. Do not recursively dump SDK/prebuilt
trees.

## Hard Rules

1. P0 is plan-only. Do not edit source files, do not create patch files, do not
   apply patches, and do not fetch external assets.
2. High-risk patches, vendor BSP/firmware/bootloader/prebuilt/closed-driver work,
   signing/packaging tools, and external dependencies must not be automatically
   generated. Put them in `external_dependency_followup` and/or
   `uncertainty_ledger`.
3. `build_acceptance` covers only the target-product compile flow using existing
   OpenHarmony build scripts already present in the workspace. It must not
   install host packages, bootstrap toolchains, download prebuilts, or perform
   source checkout/sync.
4. Never infer boot, runtime, device smoke, CTS, app, driver runtime, or test
   pass from a build pass. Keep those statuses `unknown` unless explicit logs
   support them, and do not write `boot passed`, `runtime passed`, or
   `test passed`.
5. Preserve evidence-bound behavior. Every suggestion must trace to user
   requirement, source-tree evidence, meta method, case, or log. If that trace is
   absent, put the item in `uncertainty_ledger` instead of presenting it as a
   confirmed action.
6. For every requirement or modification approach you cannot confirm, write an
   `uncertainty_ledger` item with the missing evidence, risk, and next question
   or next source/log check.
7. Treat dirty workspace and binary/prebuilt records as separate evidence
   classes. Do not present a binary import as a source fix.
8. Do not promote single-scenario cases into universal methods. Use meta methods
   and conditional methods only within their declared applicability.

## Artifact Contracts

### target_profile.yaml

Include:

```yaml
artifact_type: target_profile
execution_mode: plan-only
target:
  product: unknown
  board: unknown
  soc: unknown
  vendor: unknown
  architecture: unknown
  openharmony_version: unknown
source_context:
  workspace_root: <path or unknown>
  source_output: <path or unknown>
  meta_output: <path or unknown>
requirements:
  - requirement_id: REQ-001
    description: <user or profile requirement>
    source: user_requirement|task_profile|operator_context|unknown
    evidence_refs: [...]
```

### meta_knowledge_digest.yaml

Use:

```yaml
artifact_type: meta_knowledge_digest
meta_output: <path or unknown>
target_terms: []
target_scenario_types: []
meta_status: loaded|missing|unknown
selected_methods:
  - method_id: <meta method id>
    title: <title>
    applicability: []
    evidence_strength: <strength or unknown>
    statement: <short statement>
    quality_gates: []
    risks: []
    supporting_cases: []
    selection_reason: <why this method applies>
    evidence_refs: [...]
deferred_methods: []
selected_cases:
  - case_id: <case id>
    title: <title>
    scenario_id: <scenario id>
    scenario_type: []
    subsystem: []
    porting_phase: []
    problem_type: []
    reuse_level: <reuse level>
    evidence_strength: <strength>
    rule: <case rule>
    repo_paths: []
    source_case_path: <path>
    evidence_refs: [...]
action_bias:
  - action_id: META-ACTION-001
    area: product_board_binding|riscv_build_runtime|external_dependency_governance|unknown
    recommendation: <execution guidance>
    evidence_refs: [...]
```

Select only meta methods and cases whose applicability matches the target seed,
architecture, product/board/SoC/vendor terms, or universal guardrails. Keep HDF,
WiFi, media/camera, audio, and display feature methods in `deferred_methods`
until target product/board/SoC paths and feature requirements are visible.

### target_source_evidence.yaml

Use:

```yaml
artifact_type: target_source_evidence
target: {}
target_source_root: <path or unknown>
scan_status: not_supplied|missing|loaded
visibility: {}
expected_path_count: 0
found_path_count: 0
binary_asset_count: 0
coverage_note: <bounded scan scope>
items:
  - evidence_id: TSE-001
    kind: expected_file|expected_directory|sample_source_file
    role: productdefine_config|vendor_product_config|board_config|soc_config|kernel_or_driver_payload|bootloader_packaging|unknown
    path: <path relative to target source root>
    status: found|missing
    evidence_refs: [...]
binary_assets:
  - asset_id: TSA-001
    category: bsp|bootloader|firmware|prebuilt|closed_driver|signing_packaging_tools|unknown
    path: <path relative to target source root>
    sha256: <hash or unknown>
    relation: target_source_dependency_candidate|unknown
    risk: <why provenance remains open>
    next_action: <review action>
    evidence_refs: [...]
```

This artifact is evidence only. It can improve candidate previews and dependency
inventory, but it does not authorize automatic source writes, binary imports, or
completion claims.

### source_import_plan.yaml

Use:

```yaml
artifact_type: source_import_plan
target: {}
target_source_root: <path or unknown>
scan_status: not_supplied|missing|loaded|unknown
default_write_policy: do_not_write_to_workspace
import_policy: manual_review_only
item_count: 0
excluded_dependency_count: 0
decision_counts: {}
coverage_note: <scope note>
items:
  - import_id: IMP-001
    import_class: product_config|build_manifest|board_config|soc_config|kernel_build_config|hdf_config|driver_source|product_runtime_config|other_source_file|unknown
    source_role: <role from target_source_evidence>
    source_path: <path relative to target source root or unknown>
    target_path: <workspace-relative destination path>
    target_workspace_path: <absolute destination path>
    source_status: found_in_target_source_root|missing_in_target_source_root|unknown
    current_workspace_status: missing|present_same_hash|present_different_or_unverified|present_directory|unknown
    source_sha256: <hash or unknown>
    current_sha256: <hash or unknown>
    import_decision: manual_import_candidate|compare_before_import|already_present_same_hash|cannot_import_missing_target_source|unknown
    write_policy: do_not_write_to_workspace
    apply_gate: <manual review gate>
    next_action: <next controlled step>
    evidence_refs: [...]
excluded_items:
  - excluded_id: EXCL-001
    path: <target source path>
    category: bootloader|firmware|prebuilt|closed_driver|signing_packaging_tools|external_dependency|unknown
    reason: <why this is not a source import>
    routed_to: target_dependency_inventory|external_dependency_followup
    evidence_refs: [...]
```

This artifact is the execution queue for source and compile-file work. It must
not mark items `ready_to_apply`, generate patch hunks, copy files, or treat
binary/firmware/prebuilt payloads as source imports.

### porting_work_order.yaml

Use:

```yaml
artifact_type: porting_work_order
target: {}
default_execution_policy: manual_review_only
workspace_write_policy: do_not_write_to_workspace
controlled_executor:
  tool: tools/apply_porting_base_patch.py
  default_mode: dry_run_stage_only
  allowed_phases: [L0_target_identity, L1_base_binding, L2_build_triage]
  excluded_payloads: [firmware, bootloader, prebuilt, kernel_module, closed_driver, signing_packaging_tool]
  compatibility_policy: normalize_openharmony_6_0_product_device_subsystems_preserve_product_features_apply_evidenced_riscv64_build_compat_and_generate_fake_interfaces_when_needed
  dry_run_command: <stage-only command; no workspace write>
  apply_and_build_command: <requires explicit --apply --attempt-build>
  notes:
    - build attempts must emit diagnostics that separate host/prebuilt failures from source/build compatibility and dependency follow-up
    - RISC-V build compatibility patches are allowed only when the reference target tree contains matching source evidence such as NDK riscv64 mapping, curl riscv64 cflags guards, libcpp riscv64 prebuilt source mapping, or graphic_3d rofs rv64 object mappings
    - ArkCompiler RISC-V assertion blockers may use only the target-evidenced minimal ark_config.gni LLVM backend/codegen disablement, not broad ArkCompiler source replacement
    - prebuilt-backed components should remain visible in product config where possible; use marked compile-only fake interfaces for missing external payloads
    - architecture-specific prebuilt gaps may use wrong-architecture binary placeholders only when clearly marked and reported as compile-only dependency debt
    - board vendor text closures may be imported, but firmware payloads must become tracked compile-only fake artifacts
    - board root local-module text/config closures may be imported; kernel modules, bootloader images, and firmware must become tracked fake interfaces
    - board-referenced SoC module text/source closures may be imported; firmware, GPU/WiFi blobs, and shared libraries must become tracked fake interfaces
    - vendor product module text/config closures may be imported from direct target ohos.build labels; non-text payloads must become tracked fake interfaces
    - WebView local text/source closures and their local GN/GNI support imports may be imported from target ohos_nweb GN labels after resolving webview_path-style variables; .idl and linker map files are text inputs, while prebuilts remain fake-interface debt
    - WebView app_fwk_update bundle and test labels may be migrated from the old flat sa target to target-evidenced sa/app_fwk_update to resolve duplicate-output GN collisions
    - missing source components should use zero-subcomponent fake bundle registries before product features are removed
    - missing target-evidenced component features should use tracked feature-registry shims before product features are removed
    - host C++ include/link-path gaps may be fixed by validated build-subprocess environment variables, not source edits
    - every fake interface must be reported with missing dependency, provenance path, runtime non-functionality, and replacement follow-up
batch_count: 0
source_import_item_count: 0
excluded_dependency_count: 0
acceptance_ladder: []
coverage_note: <scope note>
batches:
  - batch_id: BATCH-001
    title: <short title>
    phase: L0_target_identity|L1_base_binding|L2_build_triage|L3_runtime_hdf_config|L4_feature_driver_source|L5_external_dependency_closure|unknown
    status: blocked_missing_target_source|manual_review_ready_blocked_by_batch_001|blocked_until_base_binding_visible|deferred_until_build_triage|deferred_until_feature_and_dependency_closure|external_dependency_followup_required|unknown
    objective: <batch objective>
    import_ids: []
    target_paths: []
    prerequisites: []
    blocking_reasons: []
    verification_commands:
      - command_id: WO-CMD-001
        command: <existing check or build-only command>
        description: <what this verifies>
        runnable_now: false
        environment_setup: false
        uses_existing_script: true|false
        evidence_refs: [...]
    next_action: <next controlled step>
    evidence_refs: [...]
```

This work order sequences `source_import_plan` into execution batches. It may
name a controlled executor entrypoint, but it must not itself write files, run
commands, mark batches complete, perform environment setup, or infer
boot/runtime/test status from build-only checks.

### implementation_readiness.yaml

Use:

```yaml
artifact_type: implementation_readiness
target: {}
overall_status: blocked_before_source_implementation|ready_for_build_only_triage|unknown
completion_claim: not_complete|partial|unknown
items:
  - item_id: IMPL-001
    area: product_config|board_soc_config|riscv_build_runtime|feature_driver_runtime|vendor_binary_dependency|unknown
    implementation_class: source_compile_file|external_binary_dependency|unknown
    target_paths: []
    current_status: missing_in_workspace|visible_in_workspace|partially_visible|meta_case_identified|deferred_until_base_binding|report_only|unknown
    execution_decision: plan_ready_not_applied|manual_review_required|requires_diff_or_source_review|defer_feature_specific_source_work|do_not_generate_binary_artifacts|ready_for_build_triage|unknown
    why_not_completed: <reason or empty>
    next_action: <next reliable action>
    evidence_refs: [...]
```

This artifact must decide what can be implemented as source or compile files,
what must remain a plan, and what is blocked by vendor/BSP/binary provenance.
It must not claim the port is complete unless product, board, SoC, build, and
explicit boot/runtime/test evidence are present.

### source_file_blueprint.yaml

Use:

```yaml
artifact_type: source_file_blueprint
target: {}
default_generation_mode: blueprint_only
apply_policy: do_not_apply_without_target_source_evidence
blueprints:
  - blueprint_id: SRC-BP-001
    target_path: <repo path or route>
    owning_area: product_config|board_soc_config|riscv_build_runtime|feature_driver_runtime|unknown
    file_kind: productdefine_json|vendor_product_config_json|vendor_build_manifest|board_config_gni|board_device_gni|soc_config_gni|cross_repo_source_route|unknown
    generation_mode: blueprint_only
    content_strategy: <what the eventual source file must express>
    reference_paths: []
    required_fields: []
    target_values: {}
    apply_gate: <evidence gate before source files or patches may be generated>
    evidence_refs: [...]
```

Blueprints may describe candidate source or compile-file content strategy, but
must not write source files, patch files, or diff hunks. They are the bridge
between meta knowledge and later controlled implementation.

### source_candidate_manifest.yaml

Use:

```yaml
artifact_type: source_candidate_manifest
target: {}
default_write_policy: do_not_write_to_workspace
candidate_count: 0
scope_note: <scope note>
candidates:
  - candidate_id: SRC-CAND-001
    target_path: <repo path>
    source_blueprint_ref: SRC-BP-001
    content_format: json|gn|text|unknown
    readiness: preview_only_not_apply_ready|unknown
    write_policy: do_not_write_to_workspace
    content_preview: <concrete review-only source text>
    open_questions: []
    apply_gate: <evidence gate before writing to workspace>
    evidence_refs: [...]
```

Candidate files may include concrete source text previews for review, but must
not be written to the workspace, marked ready to apply, or encoded as patch
diffs.

### target_dependency_inventory.yaml

Use:

```yaml
artifact_type: target_dependency_inventory
target: {}
inventory_source: selected_meta_cases|selected_meta_cases_and_target_source_root|source_output|unknown
asset_count: 0
coverage_note: <scope note>
items:
  - asset_id: ASSET-001
    category: bsp|bootloader|firmware|prebuilt|closed_driver|signing_packaging_tools|unknown
    path: <asset path from evidence>
    sha256: <hash or unknown>
    relation: risk_only|runtime_dependency|unknown
    source_case_id: <case id>
    source_case_title: <case title>
    target_relevance: target_case_match|conditional_case_match|unknown
    risk: <why this remains dependency evidence>
    next_action: <provenance or validation check>
    evidence_refs: [...]
```

This inventory reports vendor, BSP, firmware, prebuilt, module, bootloader, and
packaging assets found in selected evidence. It must not imply those assets are
present in the current workspace or redistributable.

### source_tree_survey.yaml

Use:

```yaml
artifact_type: source_tree_survey
items:
  - survey_id: SURVEY-001
    topic: build_entrypoint|product_config|device_board|kernel|vendor_blob|signing_packaging|other
    status: found|missing|ambiguous|unknown
    paths: []
    observation: <bounded observation>
    evidence_refs: [...]
```

### gap_analysis.yaml

Use:

```yaml
artifact_type: gap_analysis
gaps:
  - gap_id: GAP-001
    area: product_config|board_config|kernel|hdf_driver|subsystem|binary_prebuilt|bootloader|firmware|packaging|build|unknown
    severity: blocker|high|medium|low|unknown
    description: <gap>
    owner_hint: source_patch|vendor_or_third_party|user_decision|unknown
    evidence_refs: [...]
    uncertainty_refs: []
```

### porting_plan.yaml

Use:

```yaml
artifact_type: porting_plan
phases:
  - phase_id: PHASE-001
    title: <phase>
    objective: <objective>
    prerequisites: []
    tasks:
      - task_id: TASK-001
        description: <action>
        output: <expected artifact>
        evidence_refs: [...]
    acceptance: []
    evidence_refs: [...]
case_selector:
  selected_cases: []
  selected_meta_methods: []
```

### patch_plan.yaml

Use:

```yaml
artifact_type: patch_plan
default_apply_mode: plan-only
patches:
  - patch_id: PATCH-001
    title: <candidate change>
    target_paths: []
    risk_level: low|medium|high|critical|external_dependency|unknown
    apply_mode: plan-only|manual_review|none
    auto_generate: false
    rationale: <why this is only a plan>
    evidence_refs: [...]
    blocked_by_external_dependency: false
```

Do not include diff hunks or patch contents.

### build_acceptance.yaml

Use:

```yaml
artifact_type: build_acceptance
scope: build_only
environment_setup_policy: forbidden
status_policy:
  build: planned|not_run|log_triaged|unknown
  boot: unknown
  runtime: unknown
  tests: unknown
commands:
  - command_id: BUILD-001
    command: <existing OpenHarmony build script command or unknown>
    cwd: <workspace-relative path>
    purpose: <compile-flow purpose>
    uses_existing_script: true
    environment_setup: false
    evidence_refs: [...]
log_triage:
  build_log: <path or unknown>
  findings: []
```

If no existing build script can be confirmed, set `command: unknown` and create
an uncertainty item. Do not write package-install or source-sync commands.

### external_dependency_followup.yaml

Must cover all categories even when status is `unknown` or `not_required`:

```yaml
artifact_type: external_dependency_followup
coverage:
  - category: bsp
    status: required|not_required|unknown
  - category: bootloader
    status: required|not_required|unknown
  - category: firmware
    status: required|not_required|unknown
  - category: prebuilt
    status: required|not_required|unknown
  - category: closed_driver
    status: required|not_required|unknown
  - category: signing_packaging_tools
    status: required|not_required|unknown
items:
  - dependency_id: EXT-001
    category: bsp|bootloader|firmware|prebuilt|closed_driver|signing_packaging_tools|other_third_party
    provider_hint: <SoC vendor, board vendor, third party, user, unknown>
    requested_artifact: <artifact>
    why_needed: <reason>
    required_metadata: [version, source, license, sha256, architecture, redistribution_terms]
    evidence_refs: [...]
```

### uncertainty_ledger.yaml

Use:

```yaml
artifact_type: uncertainty_ledger
items:
  - uncertainty_id: UNC-001
    topic: <requirement/change/dependency/build/log/runtime>
    unknown: <what cannot be confirmed>
    impact: blocker|high|medium|low|unknown
    next_action: <question, source check, log check, vendor follow-up>
    evidence_refs: [...]
```

## P1/P2 Notes

P1 features may be represented as plan-only fields only:

- build log triage from `PORTING_EXECUTION_BUILD_LOG`;
- case selector references from meta output;
- patch apply-mode labels in `patch_plan`, with no patch generation in P0.

P2 execution replay and runtime-log validation must remain future or unknown
unless explicit replay/runtime logs are provided. Do not claim runtime success.

## Final JSON

Return only JSON with:

```json
{
  "stage": "10_porting_execution_assistant",
  "status": "passed",
  "summary": "plan-only execution assistant artifacts generated",
  "execution_mode": "plan-only",
  "patch_apply_mode": "none",
  "artifact_root": "porting_knowledge_output/08_execution_assistant",
  "input_files_read": [],
  "output_files_written": [],
  "blocking_issues": [],
  "non_blocking_issues": [],
  "next_stage_inputs": [],
  "patch_plan_item_count": 0,
  "external_dependency_followup_count": 0,
  "uncertainty_count": 0
}
```
