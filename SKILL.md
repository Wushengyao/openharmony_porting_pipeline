---
name: openharmony_porting_pipeline
description: Run the Wushengyao OpenHarmony porting pipeline to extract evidence-bound board/SoC porting knowledge, generate reusable porting skill artifacts, audit outputs, and export cross-scenario meta inputs.
---

# OpenHarmony Porting Pipeline

Use this Skill when the user asks to run, install, operate, inspect, or reuse the
`Wushengyao/openharmony_porting_pipeline` workflow.

This skill directory contains the upstream repository:

- `tools/`: pipeline runners, deterministic extraction scripts, validators, and aggregators.
- `prompts/`: isolated Codex prompts for stages `00` through `08` and auxiliary stages.
- `schemas/`: JSON schemas used by stage validation.
- `docs/`, `examples/`, and `references/`: usage notes and supporting rules.

## Common Commands

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

Run the plan-only execution assistant after the evidence pipeline:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_porting_execution_assistant.sh \
  --source-output /path/to/ohos/porting_knowledge_output \
  --meta-output /path/to/openharmony_porting_meta_output_or_zip \
  --target-profile /path/to/target_profile_seed.yaml \
  --target-source-root /path/to/reference_target_ohos \
  /path/to/ohos
```

Stage, apply, and optionally compile-test the reviewed L0/L1 base patch:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/apply_porting_base_patch.py \
  --workspace /path/to/ohos \
  --target-source-root /path/to/reference_target_ohos \
  --target-profile /path/to/target_profile_seed.yaml \
  --out /path/to/ohos/porting_knowledge_output/base_patch_apply \
  --apply \
  --attempt-build
```

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

## Operating Rules

- Keep stage isolation: pass files and stage results between stages, not full chat history.
- Treat repository records, diffs, manifests, binary hashes, dirty workspace records, and logs as evidence.
- Keep operator context as user-supplied hints; if it conflicts with repository evidence, record the conflict and prefer verifiable evidence.
- Preserve unknowns instead of inventing build, boot, runtime, provenance, or validation status.
- Do not promote force-sync SDK commits, initial imports, `.gitattributes`-only commits, dirty workspace files, or binary imports into reusable source-fix cases.
- In cross-scenario output, distinguish `universal_by_design` pipeline guardrails from `universal_from_evidence` case/pattern-derived methods; do not use a bare `universal` label.
- Generate and validate cross-scenario `conditional` methods in `02_patterns/conditional_methods.jsonl` with `derivation=conditional_from_evidence` when evidence clusters span multiple scenarios.
- Keep conditional method boundaries precise: HDF driver, media/camera HDF, binary/prebuilt provenance, and dirty workspace governance are separate clusters.
- Preserve direct machine traceability from meta methods to source support by emitting `meta_method_to_case` and `meta_method_to_pattern` rows.
- Keep case `scenario_type` values within the registry labels for that `scenario_id`; use `scenario_shape` for synthesized labels.
- Keep `evidence_type` / `evidence_level` separate from `evidence_strength`.
- Retain LLM refinement status files even when deterministic aggregation is used without `--llm-refine`.
- During `--llm-refine`, protect `cross_scenario_result.json` machine counts and restore deterministic output if Codex refinement fails.
- Use `porting_knowledge_output/` as the default output root unless the user specifies another directory.
- Prefer the repository scripts over hand-written ad hoc extraction or validation.
- The execution assistant is a post-pipeline layer. It defaults to plan-only,
  must not auto-generate high-risk patches or external dependency artifacts,
  and must not infer boot/runtime/test pass from build pass.
- Use `implementation_readiness` and `porting_completion_summary` to separate
  source/compile files that are ready to implement from vendor/BSP/binary
  dependencies and incomplete validation states.
- Use `source_file_blueprint` as the non-mutating bridge from meta knowledge to
  later controlled source or compile-file implementation.
- Use `source_candidate_manifest` for concrete review-only file previews; keep
  its write policy disabled until target source evidence closes the apply gate.
- Use `target_source_evidence` when a read-only reference target source tree is
  supplied; it may inform candidate previews and dependency inventory, but does
  not authorize copying files into the workspace.
- Use `source_import_plan` to convert read-only target-source text evidence into
  a manual-review import queue while excluding binary, firmware, bootloader,
  module, prebuilt, and packaging dependencies from source imports.
- Use `porting_work_order` to sequence source-import items into manually
  reviewable execution batches with prerequisites, blockers, and build-only
  verification commands.
- Use `apply_porting_base_patch.py` only after the target seed and target source
  evidence identify concrete L0/L1 text files. Its default mode stages files
  under the output directory without workspace writes; `--apply` is required for
  source edits and `--attempt-build` is allowed only after apply.
- Keep its OpenHarmony 6.0 subsystem-name normalization enabled unless the user
  explicitly needs byte-for-byte target-source staging; this adapts copied
  product/device `ohos.build` files to `product_<product>` and `device_<board>`
  preloader paths before compile triage.
- Preserve target product/vendor component and feature declarations by default.
  Use component visibility filtering only as an explicit diagnostic mode after
  recording why a missing source component cannot be represented by a text
  closure or fake interface.
- Include the board root `BUILD.gn` in the base patch when `device/board/.../ohos.build`
  directly references a board group; leave feature subdirectories, firmware, and
  runtime/HDF payloads to build-log-driven follow-up batches.
- Keep product and board feature declarations visible where possible. When a
  build blocker is caused by a missing binary/prebuilt/third-party payload,
  prefer a clearly marked compile-only fake interface over removing the feature
  from product config; summarize every fake in dependency debt reports.
- For RISC-V targets, allow the controlled executor to stage/apply a minimal
  `build/ohos/ndk/ndk.gni` compatibility patch only when the reference target
  source tree contains the `riscv64-linux-ohos` NDK mapping evidence.
- For RISC-V targets, allow the controlled executor to stage/apply the
  `third_party/curl/BUILD.gn` riscv64 cflags guard only when the reference
  target source tree contains the same guard.
- For RISC-V targets, allow the controlled executor to stage/apply
  `build/common/libcpp/BUILD.gn` libc++ prebuilt source mapping only when the
  reference target source tree contains the riscv64 rule; if the payload is
  absent, represent it as tracked compile-only dependency debt.
- Treat `base_patch_manifest` build diagnostics as the next iteration driver:
  separate host/prebuilt toolchain issues from source/build compatibility,
  missing text closures, product-config version skew, and external dependency
  follow-up.
- When a compile blocker is backed by a target prebuilt such as WebView
  `ArkWebCore.hap`, keep `web:webview` selected and generate a tracked
  compile-only fake artifact only as a build-progress bridge. Record the
  reference path, hash, fake path, runtime non-functionality, and replacement
  follow-up in `base_patch_manifest`.
- For WebView RISC-V build rules copied from target `ohos_nweb`, import direct
  local text/source closures after resolving `webview_path` GN labels, and carry
  local GN/GNI support files imported by those modules; treat `.idl` and linker
  map files as text closure inputs, while prebuilt payloads remain
  fake-interface dependency debt.
- When target evidence moves WebView `app_fwk_update` from the old flat `sa`
  target to `sa/app_fwk_update`, migrate WebView bundle labels to the new module
  and import the matching app_fwk_update unit-test text closure instead of
  building both services and producing duplicate shared-library outputs.
- For architecture-specific prebuilt rules such as RISC-V Rust
  `libstd.dylib.so`/`libtest.dylib.so`, import only the evidenced text build
  rule and use clearly marked wrong-architecture binary placeholders when the
  real target prebuilt is unavailable. These placeholders are compile-only and
  must be replaced before packaging/runtime validation.
- For ArkCompiler RISC-V assertion blockers, apply only the target-evidenced
  minimal `ark_config.gni` rule that disables unsupported LLVM
  backend/irtoc/codegen paths for `target_cpu == "riscv64"`; avoid importing the
  broader ArkCompiler 6.1 source rename set during base compile triage.
- For SmartPerf split blockers, when target evidence shows SmartPerf is owned by
  `developtools/smartperf_host`, remove legacy `developtools/profiler/host/smartperf`
  labels from the hiprofiler bundle registry to avoid duplicate fuzz outputs.
- For board vendor modules, import text-only C/GN/header closures when directly
  referenced by board manifests, while representing firmware payloads such as
  Bluetooth `.hcd` files with tracked compile-only fake artifacts.
- For local modules directly listed by `device/board/<vendor>/<board>/BUILD.gn`,
  import text/config closures, but represent kernel modules, bootloader images,
  firmware, and other non-text payloads as tracked compile-only fake interfaces.
- When Ninja reports missing board `audio_alsa` sources, import the
  target-evidenced `device/board/<vendor>/<board>/audio_alsa` text/source
  closure instead of removing the audio adapter feature; keep any non-text
  payloads as fake-interface dependency debt.
- When Ninja reports a missing `kernel/linux/<board-kernel>` BSP source tree,
  keep image generation enabled and use a tracked fake kernel-source marker plus
  a `build_kernel.sh` fake-output bridge for compile triage; report the real
  board kernel source as unresolved BSP dependency debt.
- For SoC modules under `device/soc/<soc_vendor>/<soc>` directly referenced by
  the board root `BUILD.gn`, import text/source closures and represent firmware,
  proprietary GPU/WiFi blobs, and shared-library payloads as tracked
  compile-only fake interfaces.
- For vendor product modules directly listed by `vendor/<vendor>/<product>/ohos.build`,
  import text/config closures such as image config, preinstall config, HDF `.hcs`,
  XML, JSON, `.para`, GN/GNI, and C/header files; represent non-text payloads as
  tracked compile-only fake interfaces.
- For RISC-V graphics builds, add target-evidenced `graphic_3d` rofs `rv64`
  object mappings to compile files when GN reports empty generated asset paths;
  this is a build-compatibility source fix, not a product feature removal.
- For RISC-V resource object generation, add target-evidenced
  `build/scripts/run_objcopy.py` `riscv64` output/BFD mappings when Ninja
  reports `KeyError: 'riscv64'` from `run_objcopy.py`.
- Preserve target-evidenced executable bits for build scripts invoked directly
  through `/usr/bin/env`, such as `param_fixer.py` and board
  `build_kernel.sh`; content-identical files may still need a mode-only update.
- When a product references a component that has no real current-workspace
  `bundle.json`, generate a zero-subcomponent fake component registry under
  that subsystem's root from `build/subsystem_config.json` instead of deleting
  the component from product config. Treat this as source/dependency debt.
- When a product references a feature that the current component registry lacks
  but the target reference declares, add a tracked feature-registry shim to the
  component `bundle.json` instead of removing the product feature.
- If prebuilt host clang selects an incomplete host GCC installation and cannot
  include `<cstdlib>` or cannot link `-static-libstdc++`, validate the detected
  host paths, but do not export host `CPLUS_INCLUDE_PATH` globally into a target
  product build. Treat host include paths as probe-only unless a later host-only
  scope is available; `LIBRARY_PATH` may be exported after validation. Record
  this as an environment-scope fix, not a source patch.
- Use `target_dependency_inventory` to summarize binary, firmware, bootloader,
  prebuilt, and closed-driver candidates from selected evidence without
  promoting them to source fixes.

Cross-scenario aggregation now emits `meta_skill_pack/` with installable
`SKILL.md` drafts plus `_validate_meta_output.log` for the validation transcript.

## Stage Order

1. `00_scope_classifier`
2. `01_repo_baseline_extractor`
3. `02_raw_record_extractor`
4. `aux_dirty_workspace`
5. `aux_binary_asset_auditor`
6. `03_statistics_qc`
7. `04_semantic_analyzer`
8. `05_case_kb_builder`
9. `06_skill_generator`
10. `07_final_auditor`
11. `08_meta_input_exporter`
12. Optional `10_porting_execution_assistant`

For deeper usage details, read `README.md` in this skill directory first, then
open only the specific tool, prompt, schema, or reference needed for the user's
requested stage.
