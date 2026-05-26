# OpenHarmony Porting Pipeline

Evidence-bound pipeline for extracting reusable OpenHarmony board/SoC porting knowledge from a repo-managed workspace.

## Goal

The pipeline classifies the porting scenario, extracts repo and raw change records, audits dirty workspace and binary assets, computes statistics, builds semantic and case knowledge, generates a reusable Skill, runs a final audit, and exports normalized single-scenario inputs for cross-scenario aggregation.

This project is not T113-only. T113/T113-S3 rules are guardrails for a common ARM-primary + auxiliary-core pattern and for the current sample workspace; concrete board/SoC names must come from `task_profile.yaml`, raw records, cases, and optional operator context.

The design goal is **stage isolation**: each stage has its own Codex context and passes only files, summaries and stage results to the next stage.

## Typical Usage

```bash
bash tools/run_pipeline.sh /path/to/ohos
```

Run in human-collaboration mode:

```bash
bash tools/run_pipeline.sh --mode collab /path/to/ohos
```

Run the full pipeline and export cross-scenario meta inputs explicitly:

```bash
bash tools/run_pipeline.sh --export-meta /path/to/ohos
```

Skip the meta export stage when only the v4 single-scenario output is needed:

```bash
bash tools/run_pipeline.sh --no-export-meta /path/to/ohos
```

Equivalent environment form:

```bash
PIPELINE_MODE=collab bash tools/run_pipeline.sh /path/to/ohos
```

Run one stage:

```bash
bash tools/run_stage.sh /path/to/ohos 03_statistics_qc
```

Export normalized cross-scenario inputs for an existing single-scenario output:

```bash
bash tools/run_stage.sh /path/to/ohos 08_meta_input_exporter /path/to/ohos/porting_knowledge_output
```

Aggregate multiple scenarios into a meta knowledge base:

```bash
bash tools/run_cross_scenario_aggregator.sh \
  --input scenario_outputs/t113/porting_knowledge_output \
  --input scenario_outputs/ruyios/porting_knowledge_output \
  --out openharmony_porting_meta_output
```

Or discover inputs under a root:

```bash
bash tools/run_cross_scenario_aggregator.sh \
  --input-root scenario_outputs \
  --out openharmony_porting_meta_output
```

Hide absolute local source paths in shareable meta output:

```bash
bash tools/run_cross_scenario_aggregator.sh \
  --input-root scenario_outputs \
  --out openharmony_porting_meta_output \
  --redact-local-paths
```

Optional LLM refinement after deterministic aggregation:

```bash
bash tools/run_cross_scenario_aggregator.sh \
  --input-root scenario_outputs \
  --out openharmony_porting_meta_output \
  --llm-refine
```

Every cross-scenario aggregation retains LLM refinement status files. Deterministic
runs write `_llm_refine_result.json`, `_llm_refine.ndjson`, and a
`_codex_logs/09_cross_scenario_refine.skipped.json` marker; `--llm-refine`
overwrites those with the Codex refinement result and NDJSON log when available.
The runner preserves `cross_scenario_result.json` machine counts across LLM
refinement and restores deterministic output if the Codex refine process fails.

See `docs/CROSS_SCENARIO_USAGE.md` for a compact usage guide.

Run the plan-only OpenHarmony porting execution assistant after a single
scenario output and, optionally, cross-scenario meta output are available:

```bash
bash tools/run_porting_execution_assistant.sh \
  --source-output /path/to/ohos/porting_knowledge_output \
  --meta-output /path/to/openharmony_porting_meta_output_or_zip \
  --target-profile /path/to/target_profile_seed.yaml \
  --target-source-root /path/to/reference_target_ohos \
  /path/to/ohos
```

The execution assistant is not part of the default `run_pipeline.sh` flow. It
writes plan-only execution artifacts under:

```text
/path/to/ohos/porting_knowledge_output/08_execution_assistant/
├── target_profile.yaml
├── meta_knowledge_digest.yaml
├── meta_knowledge_digest.md
├── target_source_evidence.yaml
├── target_source_evidence.md
├── source_import_plan.yaml
├── source_import_plan.md
├── porting_work_order.yaml
├── porting_work_order.md
├── implementation_readiness.yaml
├── implementation_readiness.md
├── source_file_blueprint.yaml
├── source_file_blueprint.md
├── source_candidate_manifest.yaml
├── source_candidate_manifest.md
├── source_tree_survey.yaml
├── source_tree_survey.md
├── gap_analysis.yaml
├── gap_analysis.md
├── porting_plan.yaml
├── porting_plan.md
├── patch_plan.yaml
├── patch_plan.md
├── build_acceptance.yaml
├── build_acceptance.md
├── external_dependency_followup.yaml
├── external_dependency_followup.md
├── target_dependency_inventory.yaml
├── target_dependency_inventory.md
├── porting_completion_summary.md
├── uncertainty_ledger.yaml
└── uncertainty_ledger.md
```

P0 execution-assistant guardrails:

- default `plan-only`; no source edits, patch files, external downloads, or
  automatic high-risk patch generation;
- build acceptance is compile-flow only and may use only existing OpenHarmony
  build scripts already present in the workspace;
- vendor/third-party BSP, bootloader, firmware, prebuilt, closed driver, and
  signing/packaging tool needs go to `external_dependency_followup`;
- cross-scenario meta methods and target-matching cases are summarized in
  `meta_knowledge_digest` before they influence porting plans;
- an optional `--target-source-root` is scanned read-only and only along
  target-relevant product, board, and SoC paths;
- `source_import_plan` turns target-source text evidence into a manual-review
  import queue and routes firmware, bootloader, modules, and prebuilts away from
  source imports;
- `porting_work_order` sequences the import queue into productdefine, base
  binding, build-only triage, runtime/HDF, driver-source, and dependency-closure
  batches without writing the workspace;
- source/compile implementation readiness and current completion judgment are
  separated from external binary dependency follow-up;
- source-file blueprints bridge meta knowledge to later controlled
  implementation without writing source files or patch hunks;
- source candidate manifests include concrete review-only file previews while
  keeping workspace writes disabled;
- target dependency inventory reports binary/prebuilt/firmware candidates from
  selected evidence without treating them as source fixes;
- unknown requirements and uncertain changes go to `uncertainty_ledger`;
- build success must not be promoted to boot/runtime/test success;
- every recommendation must carry evidence references to user requirements,
  source tree evidence, meta methods, cases, or logs.

After the plan-only artifacts are reviewed, a narrow controlled executor can
stage or apply the first product-visible patch:

```bash
python3 tools/apply_porting_base_patch.py \
  --workspace /path/to/ohos \
  --target-source-root /path/to/reference_target_ohos \
  --target-profile /path/to/target_profile_seed.yaml \
  --out /path/to/ohos/porting_knowledge_output/base_patch_dry_run
```

Dry-run mode writes `base_patch_manifest.yaml`, `base_patch_manifest.md`, and
`staged_files/` without changing the workspace. To write the L0/L1 files and
run compile-flow triage:

```bash
python3 tools/apply_porting_base_patch.py \
  --workspace /path/to/ohos \
  --target-source-root /path/to/reference_target_ohos \
  --target-profile /path/to/target_profile_seed.yaml \
  --out /path/to/ohos/porting_knowledge_output/base_patch_apply \
  --apply \
  --attempt-build
```

The executor only handles productdefine, vendor product config, board binding
config, the board root `BUILD.gn`, SoC binding config, direct product
inheritance JSON, and narrowly evidenced build-compatibility fixes needed for
the selected architecture. It excludes firmware, bootloader, prebuilts, kernel
modules, closed-driver payloads, and high-risk runtime imports. Existing differing workspace files block by default;
`--overwrite` requires an explicit rerun and creates backups under the output
directory. By default it also normalizes copied `ohos.build` subsystem names to
the OpenHarmony 6.0 preloader convention (`product_<product>` and
`device_<board>`); pass `--no-ohos6-subsystem-normalization` to stage the
reference files byte-for-byte instead. It preserves target product/vendor
components and feature flags by default; pass `--filter-unavailable-components`
only for a diagnostic run where missing current-workspace bundle metadata should
be filtered intentionally.
Product and board feature declarations should remain visible during compile
triage where possible. When a blocker is caused by a missing binary, prebuilt,
firmware, or third-party payload, the executor may create a clearly marked
compile-only fake interface and record it as dependency debt instead of removing
the feature from product config.
For missing `.so` payloads that participate in target linking, fake interfaces
must be target-architecture ELF shared-library stubs rather than text marker
files. When the reference target binary is available, the executor derives
compile-only stub symbols from its dynamic symbol table and still records the
real vendor/third-party payload as unresolved runtime dependency debt.
When a selected product component has no real current-workspace `bundle.json`,
the executor can add a zero-subcomponent fake registry under that subsystem's
root from `build/subsystem_config.json` (for example `third_party/...` for
`thirdparty` and `drivers/...` for `hdf`); this keeps the product selection
intact while making the missing source/component dependency explicit in
`fake_interfaces`.
When a selected product feature is present in the target reference but missing
from the current component registry, the executor can add a tracked
feature-registry shim to the component `bundle.json` rather than removing that
feature from product config.
For a RISC-V target, if the reference target tree contains the OpenHarmony NDK
`riscv64-linux-ohos` mapping, the executor can stage/apply the corresponding
minimal `build/ohos/ndk/ndk.gni` compatibility patch; it can also apply the
evidenced `third_party/curl/BUILD.gn` riscv64 cflags guard and
`build/common/libcpp/BUILD.gn` libc++ prebuilt source mapping when needed. It
also adds target-evidenced `graphic_3d` rofs `rv64` object mappings when GN
reports empty generated asset paths for RISC-V graphics builds, and
target-evidenced Lume rofs asset-compiler riscv64 support when
`CompilerAsset.sh` reports `Invalid argument!` while generating `rofs_rv64.o`;
the executor now also declares the Lume host asset-compiler source inputs and
cleans a stale generated `LumeAssetCompiler` binary when patched sources support
`-riscv64` but the old tool does not. If a generated `*_rv64.o` rofs object
later causes a mixed floating-point ABI link in a `graphic_3d` Lume shared
library, the executor sets the generated RISC-V ELF flags to
`EF_RISCV_RVC | EF_RISCV_FLOAT_ABI_DOUBLE` and removes stale generated rv64
rofs objects before rebuilding.
It also adds
target-evidenced `build/scripts/run_objcopy.py` riscv64 mappings when resource
object generation raises `KeyError: 'riscv64'`. The same mapping is applied to
local subsystem helpers such as
`foundation/arkui/ace_engine/build/tools/run_objcopy.py` when they hit the same
architecture key gap. If `third_party/libunwind` references missing
`src/riscv/Los-linux.c`, the executor applies the target-evidenced removal from
RISC-V source lists after confirming the shared libunwind archive lacks that
file. If FFRT public headers trip the `unsupported architecture` guard for
`ffrt_fiber_storage_size`, the executor adds the target-evidenced `__riscv`
storage-size branch without importing broader 6.1 API enum changes. It also
handles the follow-on FFRT coroutine `STACK_MAGIC` RISC-V branch,
`task_client_adapter.h`'s `CTC_QUERY_INTERVAL` architecture guard, and
`cj_environment`'s `APP_USE_RISCV64`/`APP_LIB_NAME "riscv64"` platform mapping
when those errors appear. When TEE `teecd` agents still contain ARM-only
`isb`/`dsb sy` barriers, the executor applies the target-evidenced
aarch64/riscv guard in `secfile_load_agent.c`, `fs_work_agent.c`, and
`misc_work_agent.c`, using `fence.i` and `fence iorw, iorw` for RISC-V instead
of hiding the TEE feature. If musl `libc.so` linking reports mixed riscv64
floating-point ABI objects, the executor aligns musl compile/link cflags,
musl hook LTO cflags, and global riscv64 compiler/linker flags with the target-evidenced
`-march=rv64imafdc`/`-mabi=lp64d` ABI. When all explicit response-file,
CRT-object, and archive inputs are already `lp64d` but LLD still emits mixed-ABI
`lto.tmp` objects, it uses musl's existing `musl_use_flto` switch to disable
riscv64 shared-musl LTO as a compile-only compatibility bridge instead of
removing musl or target libraries. If the same mixed-ABI error then appears
across ordinary riscv64 executables/shared libraries through `lto.tmp` or
`thinlto-cache`, the executor disables the default riscv64 ThinLTO path in
`build/config/compiler/compiler.gni` as an optimization-only off-ramp for the
OpenHarmony 6.0 clang/lld stack. For Rust targets that fall back to host `cc`
while carrying riscv64 linker flags, it imports the target-evidenced
`rustc-riscv` toolchain mapping and uses an executable compile-only fake Rust
driver when the real prebuilt compiler is unavailable, recording that fake as
dependency debt. That fake driver emits RISC-V archives/shared objects and
exports `#[no_mangle] extern fn` symbols discovered in the Rust source so C/C++
links can continue; stale non-RISC-V Rust archives under `out/<product>/obj`
are removed before rebuild when the fake driver is active. Build attempts emit diagnostics
in `base_patch_manifest.yaml` and `.md` for known blockers such as
host/prebuilt C++ header gaps, missing `BUILD.gn` closures, unavailable product
components, RISC-V build-compatibility gaps, directly invoked script executable
bit mismatches, Ninja missing-source follow-ups, hb `error.log` masking
failures, and prebuilt-backed feature blockers such as a WebView riscv64
ArkWebCore HAP.
The apply step preserves target-evidenced executable bits for scripts invoked
through `/usr/bin/env`; content-identical files such as `param_fixer.py` or a
board `build_kernel.sh` may still receive a mode-only update.
For the WebView riscv64 ArkWebCore gap, the executor keeps `web:webview` enabled,
imports the evidenced text-only build rule, writes a marked compile-only fake
`ArkWebCore.hap`, imports direct local WebView text/source closures from target
`ohos_nweb` GN labels after resolving `webview_path` variables, and carries the
local GN/GNI support files those modules import. Text closures include `.idl`
and linker map files. Fake WebView payloads are reported under `fake_interfaces`.
When target evidence shows `app_fwk_update` moved from the old flat `sa` target
to `sa/app_fwk_update`, the executor rewrites WebView bundle labels to the new
module and imports the matching app_fwk_update unit-test text closure so tests
do not keep the old service target alive and duplicate
`libapp_fwk_update_service.z.so`.
External-prebuilt component deferral is now opt-in via
`--defer-external-prebuilt-components` for cases where an operator explicitly
wants that older compile-triage mode.
For RISC-V Rust std/test dylib gaps, the executor imports the target-evidenced
text GN rule and may copy an existing workspace Rust dylib as a clearly marked
wrong-architecture placeholder under `prebuilts/rustc-riscv/...`; this is only a
compile-flow bridge and is reported as fake dependency debt.
If a Rust staticlib such as `librust_hash_signed_data.a` later fails with
`is incompatible with elf64lriscv`, the executor diagnoses it as stale or
host-built Rust output, removes the wrong-architecture archive before the next
build, and relies on the fake driver or real `rustc-riscv` to regenerate it.
For ArkCompiler RISC-V GN assertion gaps, the executor may apply the
target-evidenced minimal `ark_config.gni` rule that disables unsupported
LLVM backend/irtoc/codegen paths for `target_cpu == "riscv64"`; it does not
import the broader 6.1 ArkCompiler source rename set as part of the base patch.
For ArkCompiler RISC-V target-definition gaps, the executor may also apply
target-evidenced minimal `static_core/BUILD.gn` `PANDA_TARGET_RISCV64` defines
and a `libpandabase/cpu_features.h` cache-line-size condition, again avoiding
the broader 6.1 `libarkbase` rename set during base compile triage.
For SmartPerf split conflicts, the executor may remove legacy
`developtools/profiler/host/smartperf` labels from `developtools/profiler`
`bundle.json` when target evidence shows SmartPerf is owned by
`developtools/smartperf_host`, avoiding duplicate `SpDaemonFuzzTest` outputs.
For board-level vendor Bluetooth modules, the executor imports text C/GN/header
closures referenced by `ohos.build`, but replaces firmware payloads such as
`BCM4362A2.hcd` with marked compile-only fake artifacts.
For local modules directly listed by `device/board/<vendor>/<board>/BUILD.gn`,
the executor imports text/config closures and records kernel modules, bootloader
images, firmware, and other non-text payloads as compile-only fake interfaces.
When Ninja reaches board `audio_alsa` adapter objects and reports missing C
sources, the executor imports the target-evidenced
`device/board/<vendor>/<board>/audio_alsa` text/source closure rather than
removing the audio feature; any non-text payloads remain fake-interface debt.
When Ninja needs a missing `kernel/linux/<board-kernel>` BSP source tree, the
executor keeps product image generation visible by adding a tracked fake
kernel-source marker and a target-derived `build_kernel.sh` fake-output bridge;
the real board kernel source remains dependency debt for provenance review.
For SoC modules under `device/soc/<soc_vendor>/<soc>` directly referenced by the
board root `BUILD.gn`, the executor imports text/source closures and records
firmware, proprietary GPU/WiFi blobs, and shared-library payloads as
compile-only fake interfaces. Vendor shared libraries are represented as
target-architecture linkable ELF stubs, not copied binaries, and remain runtime
dependency debt.
When imported vendor/board/SoC targets trip compile-standard part/subsystem
checks, the executor merges only matching target-evidenced
`build/compile_standard_whitelist.json` entries in the target product, board,
and SoC label spaces, keeping product component selection visible.
For vendor product modules directly listed by `vendor/<vendor>/<product>/ohos.build`,
the executor imports text/config closures (image config, preinstall config,
HDF `.hcs`, XML, JSON, `.para`, GN/GNI, C/header files) and records non-text
payloads as compile-only fake interfaces; `.so` payloads use linkable ELF stubs
when needed for compile progress.
Each base patch manifest also groups compile-only fake interfaces into a
dependency-debt summary (kernel/BSP, boot firmware, kernel modules, SoC
proprietary payloads, WebView/prebuilt apps, Rust/toolchain, fake component
registries, and other fakes) so build progress is not confused with runtime
dependency completion.
Host/prebuilt tool failures stay out of fake dependency debt: for app packaging,
the executor resolves `compile_app.py`'s `ohpm` invocation from the
OpenHarmony source root before changing into module directories, using the real
workspace command-line-tool prebuilt when present. Build attempts also emit
lightweight regression checks: `llvm-readelf -h` verifies generated fake shared
library ELF machine/ABI, fake Rust archives are scanned for non-RISC-V objects,
and old build-log blockers such as the rvbook bluetooth whitelist mismatch are
checked for absence.
When ArkCompiler static_core reaches RISC-V runtime compilation, the executor
adds the target-evidenced minimal runtime support set: RISC-V `Arch` and
`ArchTraits` mapping, runtime/fiber/signal context mappings, RISC-V runtime
assembly sources, `THREAD_REG`/`MAKE_ASM_NAME` assembly macro support, and
guarded object accessor overloads. These are treated as source compatibility
patches, not product feature filtering. If
`cross_values_generator.rb` receives no arch-name for RISC-V, the executor may
also add the target-evidenced `cross_values/BUILD.gn` `RISCV64` arch mapping
without importing unrelated ArkCompiler 6.1 rename churn.
If RISC-V bridge assembly later reports tp-relative ManagedThread offsets
outside the signed 12-bit immediate range, the manifest classifies that as a
source/build compatibility blocker for a target-scoped large-offset helper, not
as external binary dependency debt.
Build attempts also probe the prebuilt host clang C++ standard-library include
path. If clang selected an incomplete host GCC installation, the executor
validates the candidate paths and scopes them to `build/toolchain/linux:clang_x64`
through `extra_cxxflags`/`extra_ldflags`; it keeps `CPLUS_INCLUDE_PATH`
probe-only for target product builds because a global host include path can
contaminate riscv64 musl/libcxx compiles. A validated `LIBRARY_PATH` may still
be exported for host `-static-libstdc++` link repair, and the manifest records
the environment-scope decision.

Minimum local checks for the new execution-assistant layer:

```bash
bash -n tools/run_porting_execution_assistant.sh
python3 -m py_compile tools/apply_porting_base_patch.py
python3 -m py_compile tools/validate_porting_execution_assistant.py
python3 -m json.tool schemas/porting_execution_assistant.schema.json >/dev/null
python3 tools/validate_porting_execution_assistant.py \
  --workspace "$PWD" \
  --out "$PWD/porting_knowledge_output" \
  --stage-result "$PWD/porting_knowledge_output/_stage_results/10_porting_execution_assistant.json"
```

The default output directory is:

```text
/path/to/ohos/porting_knowledge_output
```

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

Optional post-pipeline execution assistance:

12. `10_porting_execution_assistant` via
    `tools/run_porting_execution_assistant.sh` or `tools/run_stage.sh`.

Stage 08 writes:

```text
porting_knowledge_output/07_meta_inputs/
├── scenario_card.yaml
├── normalized_cases.jsonl
├── pattern_candidates.jsonl
├── anti_patterns.jsonl
├── method_fragments.jsonl
├── validation_status.yaml
└── meta_input_audit.md
```

The cross-scenario aggregator reads only these compact normalized inputs. If an input lacks `07_meta_inputs`, run Stage 08 first; the aggregator intentionally does not parse old Markdown-only outputs.

Cross-scenario aggregation writes globally unique method fragment identifiers and slim evidence traces:

```text
02_patterns/method_fragments.jsonl        # includes global_method_fragment_id
04_global_kb/evidence_index.jsonl         # full evidence by evidence_ref
04_global_kb/evidence_trace_index.jsonl   # trace_id + evidence_ref links, no embedded evidence blobs
```

The trace index includes direct `meta_method_to_case` and
`meta_method_to_pattern` rows for every meta method with supporting cases or
patterns.

## Operating Modes

- `auto` (default): the pipeline runs from start to finish without asking questions. It writes `00_config/operator_context.*` with unknown/default answers so every later stage has an explicit "no human supplement" record.
- `collab`: before stage 00, the pipeline asks concise questions about project background, before/after porting boundaries, known porting commits, dirty workspace policy, binary provenance, and knowledge priorities. Blank or "unknown" answers are accepted and do not block the run.

Human answers are saved as:

```text
porting_knowledge_output/00_config/operator_context.md
porting_knowledge_output/00_config/operator_context.json
porting_knowledge_output/00_config/operator_context.yaml
```

Operator context is a hint, not repository evidence. If it conflicts with git/repo evidence, later stages should record the conflict and prefer verifiable evidence.

User-facing collaboration prompts are Chinese. Unknown answers are accepted and represented as `unknown`.

## Chinese Result Views

Each successful stage writes a Chinese stage summary:

```text
porting_knowledge_output/_stage_results/<stage>.zh.md
```

After a full pipeline run, the overall Chinese summaries are:

```text
porting_knowledge_output/06_audit/pipeline_summary.zh.md
porting_knowledge_output/06_audit/stage_results.zh.md
```

The Chinese summaries are for human review. The JSON stage results and statistics files remain the machine-readable source of truth.

## Deterministic and LLM Stages

The data-heavy stages are deterministic by default where repeatability is more important than prose quality:

- `02_raw_record_extractor`: `tools/extract_raw_records.py`
- `aux_dirty_workspace`: `tools/analyze_dirty_workspace.py`
- `aux_binary_asset_auditor`: `tools/audit_binary_assets.py`
- `03_statistics_qc`: `tools/aggregate_stats.py`

These stages intentionally keep untracked directories bounded instead of recursively expanding SDK/prebuilt trees.

The semantic stages now default to Codex/LLM execution because prior T113 runs showed deterministic templates were structurally complete but semantically shallow:

- `04_semantic_analyzer`
- `05_case_kb_builder`
- `06_skill_generator`
- `07_final_auditor`

Deterministic fallbacks are still available for debugging or environments without model access:

```bash
DETERMINISTIC_SEMANTIC_ANALYZER=1 bash tools/run_stage.sh /path/to/ohos 04_semantic_analyzer
DETERMINISTIC_CASE_KB=1 bash tools/run_stage.sh /path/to/ohos 05_case_kb_builder
DETERMINISTIC_SKILL_GENERATOR=1 bash tools/run_stage.sh /path/to/ohos 06_skill_generator
DETERMINISTIC_FINAL_AUDIT=1 bash tools/run_stage.sh /path/to/ohos 07_final_auditor
```

Force model execution for statistics if needed:

```bash
DETERMINISTIC_RAW_RECORD_EXTRACTOR=0 bash tools/run_stage.sh /path/to/ohos 02_raw_record_extractor
DETERMINISTIC_DIRTY_WORKSPACE_ANALYZER=0 bash tools/run_stage.sh /path/to/ohos aux_dirty_workspace
DETERMINISTIC_BINARY_ASSET_AUDITOR=0 bash tools/run_stage.sh /path/to/ohos aux_binary_asset_auditor
DETERMINISTIC_STATISTICS_QC=0 bash tools/run_stage.sh /path/to/ohos 03_statistics_qc
```

## Evidence Rules

- Commit claims cite `repo_path + commit_hash`.
- File claims cite `repo_path + file_path`.
- Binary claims cite `path + sha256`.
- Dirty workspace evidence is separate from committed history.
- Statistics are copied from `02_statistics/statistics_summary.json`.
- Initial import, force-sync SDK commits and `.gitattributes`-only commits must not become reusable cases.
- T113-style ARM-primary + auxiliary-core profiles must not be silently rewritten as RISC-V-primary.
- Single-scenario cases and generated Skill output must not be promoted directly to formal universal methods.
- Build, boot, runtime and test validation must stay `unknown` unless explicit logs support a stronger status.

## Quality Gates

The validator and final auditor now block:

- statistics/raw-record count mismatch;
- empty repo/subsystem analysis;
- template-like cases;
- cases based only on force-sync or `.gitattributes` evidence;
- force-sync, initial-import, or `.gitattributes`-only commits marked as case candidates;
- subsystem analysis that stops at coarse classification buckets without feature-level files;
- case files with a secondary `Validator Evidence` block instead of the canonical `evidence:` schema;
- concrete source paths mentioned in case bodies that do not resolve to raw or dirty file records;
- passed stages whose canonical validation logs still contain failed attempts;
- HDF/WiFi/Boot/Product case titles that do not match evidence paths;
- too-short generated runbook/template/checklist files;
- generated outputs contradicting `task_profile.yaml`.
- missing or invalid `07_meta_inputs` during Stage 08;
- single-scenario normalized cases marked as `universal`;
- pattern candidates missing cross-scenario confirmation requirements;
- method fragments that reference non-existent cases or patterns.

## Logs

Stage logs are written under:

```text
porting_knowledge_output/_codex_stage_logs/
```

Each stage attempt writes attempt-scoped logs first:

```text
porting_knowledge_output/_codex_stage_logs/<stage>.<run_id>.ndjson
porting_knowledge_output/_codex_stage_logs/<stage>.<run_id>.validation.log
```

Only a validation-passed attempt is copied to the canonical paths:

```text
porting_knowledge_output/_codex_stage_logs/<stage>.ndjson
porting_knowledge_output/_codex_stage_logs/<stage>.validation.log
```

Failed attempts are moved under:

```text
porting_knowledge_output/_codex_stage_logs/_failed_attempts/<stage>/<run_id>/
```

Final summaries and auditors must read promoted stage results and canonical validation logs only. Archived failed attempts are evidence for debugging, not final pipeline status.

Stage JSON results are written under:

```text
porting_knowledge_output/_stage_results/
```

## Recommended Rerun After Updating

If raw records already exist, rerun only the semantic tail:

```bash
bash tools/run_stage.sh "$PWD" 04_semantic_analyzer porting_knowledge_output
bash tools/run_stage.sh "$PWD" 05_case_kb_builder porting_knowledge_output
bash tools/run_stage.sh "$PWD" 06_skill_generator porting_knowledge_output
bash tools/run_stage.sh "$PWD" 07_final_auditor porting_knowledge_output
bash tools/run_stage.sh "$PWD" 08_meta_input_exporter porting_knowledge_output
```
