---
name: openharmony_porting_pipeline
description: Run the Wushengyao OpenHarmony porting pipeline to extract evidence-bound board/SoC porting knowledge, generate reusable porting skill artifacts, audit outputs, export cross-scenario meta inputs, and coordinate build-server to Windows local-device automation for OpenHarmony flashing and smoke validation.
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

Run the four-tree version-upgrade porting analysis when an old completed port
must be migrated onto a newer unported OpenHarmony baseline:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_version_upgrade_porting.sh \
  --old-original /path/to/old_clean_ohos \
  --old-ported /path/to/old_ported_ohos \
  --new-original /path/to/new_clean_ohos \
  --new-workspace /path/to/new_unported_ohos
```

The four inputs mean:

- `old-original`: old clean baseline before the target board/SoC/product port.
- `old-ported`: old version after that port was completed.
- `new-original`: new clean baseline before the port.
- `new-workspace`: new version workspace that will receive the migrated port.

`old-original` must be the exact frozen pre-port baseline. Do not substitute the
latest official/vendor/community branch for the same OpenHarmony version,
because that branch may have advanced after the old port and would pollute the
old-porting delta. If the original directory is missing, point the runner at a
locked manifest from `old-ported`, or let it auto-detect
`.repo/manifests/tag/*.xml`:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_version_upgrade_porting.sh \
  --old-ported /path/to/old_ported_ohos \
  --old-baseline-manifest /path/to/old_ported_ohos/.repo/manifests/tag/manifest_tag_xxx.xml \
  --new-original /path/to/new_clean_ohos \
  --new-workspace /path/to/new_unported_ohos
```

Manifest-only mode is partial by design: it extracts old-porting deltas from
`manifest_revision..HEAD` and emits `old_original_baseline.*` with the
reconstruction command. Reconstruct and supply the exact `old-original` tree for
complete `old-original -> new-original` upstream-churn analysis.

The real dependency inventory is a YAML mapping with a `real_dependencies`
list. Each entry should name the workspace `path`, `provider`, version/source
package, license or authorization reference, sha256 when available, and
`replacement_for_fake` when the real path replaces a different fake marker such
as `kernel/linux/<board-kernel>/.openharmony_porting_fake_kernel_source`.
Inventory-backed dependencies are preserved and excluded from fake-interface
debt; missing, fake-marked, hash-mismatched, or ABI-mismatched entries block the
run. Use `--prefer-existing-real-dependencies` only after existing fake
placeholders have been reviewed or removed.

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

## Local Device Automation

When the task enters a compile -> flash -> device-smoke -> code-fix loop, use
the Windows local OpenHarmony automation service instead of assuming HDC,
serial ports, Titan flasher, or board USB devices exist on this Linux server.

Read this runbook before device operations:

```bash
cat /home/ve/.codex/skills/openharmony_porting_pipeline/docs/local_device_automation.md
```

Use the helper CLI:

```bash
export OH_AUTO_BASE_URL=${OH_AUTO_BASE_URL:-http://127.0.0.1:8787/api/v1}
export OH_AUTO_DEVICE_ID=${OH_AUTO_DEVICE_ID:-default}
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py preflight --template-id musepaper2-titan
```

`preflight ok=true` means the host, template, lock state, and submission path
are ready for a flash job. It does not prove the board is already in Titan burn
mode; `titan_burn_mode_confirmed` remains `null` because service version `0.1.0`
only exposes Titan detection inside a flash job. The authoritative burn-mode
evidence is a flash event such as `titan_fastboot_found`, followed by
`titan_flash` starting or succeeding.

For MusePaper2 Titan flashing, the template id is `musepaper2-titan`. Upload the
image when it is on this Linux server, then submit the flash job and persist the
returned `job_id`:

```bash
ARTIFACT_ID=$(python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py upload /path/to/openharmony-spacemit-k1-musepaper2.zip --id-only)
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py flash musepaper2-titan --image "$ARTIFACT_ID"
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py wait "$JOB_ID" --events --timeout-sec 1800
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py wait-connected --connect-channel usb --connect-target 0123456789ABCDEF --timeout-sec 240
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py smoke --wait-connected --connect-channel usb --connect-target 0123456789ABCDEF --set-boot-escape-ack
```

For lightweight post-boot iterations that only need to replace or inspect files
on a live OpenHarmony system, the helper exposes the service `push`, `pull`, and
`reboot` operations. For example, upload an image or diagnostic binary from the
Linux build server, push it to the device, pull a screenshot back as an artifact,
or request a normal reboot:

```bash
ARTIFACT_ID=$(python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py upload /path/to/file --id-only)
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py push /data/local/tmp/file --artifact-id "$ARTIFACT_ID" --wait --connect-channel usb --connect-target 0123456789ABCDEF
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py pull /data/local/tmp/screen.png --filename screen.png --wait --connect-channel usb --connect-target 0123456789ABCDEF
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py reboot --mode normal --wait --connect-channel usb --connect-target 0123456789ABCDEF
```

Serial console access is available through the same automation service. For the
current MusePaper2 test setup, `/capabilities` reports `COM4` at `115200`, but
always use the service defaults or pass `--port`/`--baudrate` explicitly instead
of assuming a Linux-local serial device exists:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "echo oh_auto_serial_probe" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "uname -a" --wait
```

Serial responses include command echo and shell prompts such as `#`; parse the
business output defensively. Use serial for pre-HDC boot diagnostics, especially
when a MusePaper2 image stops at the Spacemit logo.
For MusePaper2 serial command and `serial-log` boot capture, prefer
`--port COM4 --baudrate 115200`; do not reuse the HDC connection baudrate
`921600` for serial logs unless a fresh probe proves it, because it can capture
gibberish while `115200` gives a working console.

For MusePaper2 OH6.1 boot-failure iterations, the first automation milestone is
an image that avoids early kernel panic and can execute `reboot fastboot` through
HDC or serial. Preserve serial logs and notify the operator for manual reset
whenever a panic-stopped board cannot enter fastboot by command.
Use `oh_autoctl.py serial-log` to start long-running serial capture before
flashing or boot validation, then save the job id and retrieve stdout/events
with `oh_autoctl.py logs`.

When changing MusePaper2 kernel sources, do not trust a successful top-level
`build.sh` by itself. Check that `out/kernel/OBJ/<product>/...`, `Image`,
`bootfs/Image.itb`, `boot.img`, and the final zip have fresh timestamps or
different hashes. The MusePaper2 kernel build is a GN action and only reruns
for files listed in its `inputs`; if a touched kernel source is not listed,
add a narrow input entry or deliberately refresh the kernel action before
flashing. This avoids validating a stale boot image.

MusePaper2 can enter the Titan flashing mode from either HDC or the serial
console by issuing `reboot fastboot`. Prefer HDC when OpenHarmony is alive; use
serial when HDC is unavailable but the boot console is responsive:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell "reboot fastboot" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "reboot fastboot" --wait
```

For the ongoing MusePaper2 OH6.1 port, after each successful build/package,
stage the zip on the Windows host as
`F:\images\PortingTest\6.1\openharmony-spacemit-k1-musepaper2.zip` before
flashing when direct Windows-path flashing is enabled. The known-good OH6.0
control image is
`F:\images\PortingTest\6.0\openharmony-spacemit-k1-musepaper2.zip`. Check
`oh_autoctl.py capabilities` first: if `F:\images` or the exact staging
directory is not in `allowed_local_roots`, use `oh_autoctl.py upload` and flash
the artifact id instead of the direct `F:\...` path. Prefer direct `F:\images`
paths when the image is already on Windows to avoid duplicate artifact uploads.
As of service `0.1.0`, `oh_autoctl.py upload` accepts only a source file and
does not copy the Linux zip to an arbitrary `F:\images` destination; if no
Windows-side copy operation is available, upload from Linux and flash the
returned artifact id.
The helper upload path uses Python `requests` multipart first when available,
then falls back to the built-in HTTP client. If small artifact uploads succeed
but MusePaper2 image uploads fail with HTTP 400 body-parse errors or HTTP 500,
treat it as an automation-service artifact ingestion/storage issue rather than
a board flash or HDC failure. Capture `capabilities`, `status`, upload
responses, and a current `smoke` result; do not submit a flash job until an
artifact id is returned or the Windows allowed local roots include the target
image directory.
If job logs/events show `OperationalError: database or disk is full`, stop
submitting device jobs: service `0.1.0` can leave already-finished commands as
stale `running`/`queued` jobs, causing preflight to fail with
`no_running_jobs=false`. The current Windows service stores runtime data under
`F:\oh-auto-data`; the old C-drive `data\artifacts`/`data\runs` accumulation has
been cleaned and should not be used for new outputs. Free/clean old generated
artifacts/runs under the runtime `data_dir` reported by `/capabilities`,
restart the service, then require `status` to have no stale `running_jobs` and
`preflight --template-id musepaper2-titan` to return `ok=true`. Use
`oh_autoctl.py diagnose-jobs` for a read-only summary of stale job evidence.
Successful `musepaper2-titan` jobs clean extracted image directories via
`cleanup_path`; failed jobs may keep extracted data under
`F:\oh-auto-data\runs\<job_id>` for debugging.

During MusePaper2 OH6.1 boot-failure iterations, do not trust `hdc shell
reboot fastboot` process success by itself. HDC can return code 0 while all USB
and UART targets are still Offline, or while stdout contains
`ExecuteCommand need connect-key`. Treat an actual flash job that reaches
`wait_titan_fastboot` and emits `titan_fastboot_found` as the authoritative
burn-mode signal. When HDC lists multiple targets, run
`oh_autoctl.py connect --connect-channel usb --connect-target 0123456789ABCDEF`
before shell/smoke checks, or pass the same connect options to `shell`/`smoke`.
For post-flash validation, do not trust template `wait_hdc` or template smoke
steps when the event payload contains `[Empty]`; run `oh_autoctl.py
wait-connected` and then `smoke --wait-connected` so only a real
Connected/Online/Ready USB target is accepted.
For finite post-boot log snapshots on MusePaper2, prefer
`oh_autoctl.py shell "hilog -z N" --wait`; see
`docs/local_device_automation.md` before trying compound shell pipelines or
service-side long-running hilog captures.
Do not treat noisy native OpenHarmony logs as a primary porting failure without
functional correlation. Repeated I2C, battery, thermal, metadata, or parameter
warnings are detail debt when HDC smoke passes, `snapshot_display` can capture
display 0, and key services such as RenderService, AbilityManagerService,
BundleMgr, CameraService, WindowManagerService, DisplayManagerService,
PowerManagerService, BatteryService, StorageManager, and HdfDeviceServiceManager
are registered. Track those warnings in the iteration ledger, but move the
main loop to failing user-visible functions or interfaces.

The current MusePaper2 panic-automation workaround is source-level plus
product-param gated: `base/startup/init/services/modules/reboot/reboot.c`
honors `startup.init.panic.reboot_target`, and
`vendor/spacemit/musepaper2/etc/param/product_musepaper2.para` sets it to
`fastboot`. Keep the crash threshold logic intact while porting; only redirect
the final panic action so failed boots can return to Titan flashing mode.

For unstable MusePaper2 OH6.1 images, add a product-level boot escape watchdog
before asking an operator to flash when the board may be left unattended. The
watchdog should be installed from `device/board/spacemit/musepaper2/cfg` into
`/vendor/bin`, start from `init.musepaper2.cfg`, and default to armed unless
`startup.porting.boot_escape.enable=false` is explicit. While the observed boot
failure is the 84 second `sysrq triggered crash`, keep
`startup.porting.boot_escape.timeout_sec=60`,
`startup.porting.boot_escape.accept_boot_completed=false`, and
`startup.porting.boot_escape.ack=false`. A healthy UI or boot-completed property
is not enough to disarm it; only set
`startup.porting.boot_escape.ack=true` after HDC or serial command access has
been verified. On timeout or forced escape, set
`ohos.startup.powerctrl=reboot,fastboot` and keep a direct
`/system/bin/reboot fastboot` fallback so the board returns to Titan flashing
mode before the known panic window.

Never blindly resubmit a flash after a network timeout. Query the known job with
`oh_autoctl.py job "$JOB_ID"` and resume logs/events first.

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
- Four-tree version-upgrade porting is optional and plan-only by default. It
  must not change the default single-scenario pipeline behavior. Use it to
  classify `old-original -> old-ported` as old porting intent,
  `old-original -> new-original` as upstream version churn, and
  `new-original -> new-workspace` as current target-workspace drift.
- In version-upgrade mode, obtain `old-original` from the exact frozen baseline
  used before the old port. Prefer a locked repo manifest inside `old-ported`
  over downloading a moving latest release branch. Treat manifest-only baseline
  extraction as partial until the baseline checkout is reconstructed.
- During version upgrades, migrate intent rather than replaying old hunks:
  classify each old-porting item as direct review, upstream merge, retarget
  required, already in progress, external dependency follow-up, or unknown.
- Keep four-tree upgrade artifacts under `09_version_upgrade/`; they are
  evidence and work orders, not proof of completed runtime porting.
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
- When a missing `.so` participates in target linking, generate a
  target-architecture ELF shared-library stub rather than a text marker file.
  If reference target `.so` evidence exists, derive compile-only exported
  symbols from its dynamic symbol table while keeping the real binary as
  unresolved runtime dependency debt.
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
- Treat `porting_completion_summary.md` as the compact handoff artifact after
  each controlled apply/build run. It records build status, patch coverage,
  fake-interface dependency debt, external prebuilt deferrals, and the next
  validation work without requiring a reader to scan every planned action.
- Treat `dependency_request.md` as the generated external-dependency request
  list after each controlled apply/build run. It groups unresolved fake
  interfaces by dependency category and includes a `real_dependencies`
  inventory template for later vendor/BSP payload intake.
- When provenance-checked dependencies arrive, record them in a
  `real_dependency_inventory.yaml` and pass it with
  `--real-dependency-inventory`. The controlled executor must preserve matching
  real files/directories, remove stale fake kernel-source markers when a real
  BSP source tree is inventoried, and stop if the inventory path is missing,
  still fake-marked, hash-mismatched, or fails the basic target-architecture
  probe. Do not overwrite real dependencies with generated fakes.
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
- When WebView `ohos_glue` build rules fail on missing generated files under
  `gen/base/web/webview/ohos_glue`, import the target-evidenced
  `ohos_interface/BUILD.gn`, base glue support, generator scripts, and the glue
  input files listed by its prepare actions so the normal copy/translator
  pipeline regenerates them; do not fake generated `.cpp` or `.h` outputs.
- Treat Python build/generator scripts as text closure inputs. Compile-only fake
  payloads are for binary, prebuilt, firmware, kernel-module, and other non-text
  dependencies, not for `.py` source files that Ninja executes.
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
- For ArkCompiler RISC-V target-definition blockers, apply target-evidenced
  minimal `static_core/BUILD.gn` `PANDA_TARGET_RISCV64` defines and
  `libpandabase/cpu_features.h` cache-line-size compatibility rules; do not
  import the broader 6.1 `libarkbase` rename set during base compile triage.
- For ArkUI NAPI CJ RISC-V blockers, when `cj_support.cpp` reports
  `current platform not supported`, add the target-evidenced
  `NAPI_TARGET_RISCV64`/`_RISCV64_` defines and import the matching
  `cj_support.cpp` ELF typedef/LIBS_NAME support instead of disabling CJ or
  ArkUI features.
- When `arkui/ace_engine/libace_ndk.z.so` reports undefined
  `ResourceManager::GetInstance()` and `Container::CurrentIdSafely()` from
  `color.cpp`, use the target-evidenced `ACE_NDK_NO_RESOURCE_MANAGER` guard in
  `Color::UpdateColorByResourceId()` and add that define to the `ace_ndk`
  OHOS build block; do not link the full ArkUI container/resource-manager core
  closure into the NDK library.
- When `web/webview/libnweb_ohos_adapter.z.so` reports missing
  `OH_AVCODEC_*`, `OH_AVFormat_*`, or `OH_VideoDecoder_*` symbols from WebView
  media adapter sources on riscv64, add the target-evidenced riscv64
  `native_media_*` SDK library branches in
  `base/web/webview/ohos_adapter/BUILD.gn` rather than disabling WebView
  AVCodec features.
- For graphic_2d VSync RISC-V format blockers, when `VPUBI64`/`VPUBU64`
  produce `-Werror=format` for LP64 `int64_t`/`uint64_t`, apply the
  target-evidenced `vsync_log.h` branch that treats
  `(__riscv && __riscv_xlen == 64)` like the existing 64-bit `%ld`/`%lu`
  platforms.
- When `multimedia/audio_framework/libaudio_process_service.z.so` reports a
  missing `IAudioProcessStream` vtable and lld says the class is missing its
  key function, check `i_audio_process_stream.h` for non-pure default virtuals
  declared without an implementation. For the existing `EnableStandby()` default
  hook, inline a no-op default in the header so the abstract base vtable can be
  emitted, while keeping low-latency audio and `audio_process_in_server` enabled.
- When `castplus/cast_engine/libcast_engine_service.z.so` reports a missing
  `CastSessionImpl::MirrorToStreamState` vtable and lld says the class is
  missing its key function, add the missing `MirrorToStreamState`
  `Enter`/`Exit`/`HandleMessage` definitions next to the adjacent
  `StreamToMirrorState` definitions instead of disabling CastEngine.
- When `multimedia/player_framework/libsystemsoundmanager.z.so` reports
  missing `AudioDeviceDescriptor` constructors, destructor, or
  `GetDeviceStreamInfo()` from `common_napi.cpp`, add
  `audio_framework:audio_foundation` beside `audio_framework:audio_client`
  in the system sound manager JS build rule because `audio_foundation`
  exports the descriptor implementation; do not remove system sound features.
- When `arkui/ace_engine/libace.z.so` reports old pipeline/render undefined
  symbols such as `RenderNode::GetOpacity()`, `RenderBox::*`,
  `TransformConvertor::*`, `TextOverlayManager::*`, or
  `RenderFocusAnimation::*`, apply the target-evidenced OHOS `libace`
  old core/bridge closure and matching allow-multiple-definition linker flag
  instead of disabling ArkUI or faking those C++ symbols.
- When `arkui/ace_engine/libcj_frontend_ohos.z.so` reports classic CJ
  frontend undefined symbols such as `ViewStackProcessor::*`,
  `SingleChildGesture::SetChild`, or old `TapGesture`/`LongPressGesture`
  vtables, apply the target-evidenced CJ old-pipeline compatibility closure:
  add the geometry/gesture sources to the non-`ohos_ng` branch, import
  `cj_touch_event_compat.cpp` and `cj_view_stack_processor_compat.cpp`, and
  add only the needed `ACE_FORCE_EXPORT` annotations rather than disabling CJ.
- When that CJ old-pipeline closure reaches lower-level undefined symbols such
  as `SequencedRecognizer`, `ClickRecognizer`, `TouchEventTarget::*`,
  `ResSchedReport::*`, or `SoleChildElement` from `libcj_frontend_ohos.z.so`,
  export the target-evidenced symbols through `build/libace.map` and matching
  `ACE_FORCE_EXPORT` header annotations; do not fake ArkUI core classes or
  remove CJ/product features.
- When `request/request/librequest.z.so` reports missing `SHA256_Init`,
  `SHA256_Update`, or `SHA256_Final`, add `openssl:libcrypto_shared` beside
  `openssl:libssl_shared` in the request JS NAPI build rule; do not fake
  OpenSSL symbols or remove the request component.
- When `resourceschedule/background_task_mgr/libbackgroundtaskmanager.z.so`
  reports missing `JsBackgroundTaskSubscriber` methods from
  `bg_continuous_task_napi_module.cpp`, add the existing
  `napi/src/js_backgroundtask_subscriber.cpp` source and its runtime dependency
  to the same target rather than disabling background task manager NAPI.
- When notification reminder modules report missing
  `AbilityRuntime::Context::GetApplicationContext()` and
  `ApplicationContext::GetCurrentInstanceKey()` from shared `common.cpp`, add
  `ability_runtime:app_context` to the reminderagent/reminderagentmanager build
  rules because `libapp_context` exports those symbols; do not remove reminder
  or distributed notification features.
- When `usb/usb_manager/libusbservice.z.so` reports missing
  `OHOS::HDI::Usb::V1_0::IUsbInterface::Get(bool)` from
  `usb_port_manager.cpp`, add the generated
  `drivers_interface_usb:libusb_proxy_1.0` dependency because the port manager
  still uses the V1_0 HDI namespace; do not fake this symbol while the real HDI
  proxy library exists.
- When `location/location/liblbsservice_locator.z.so` reports mixed
  floating-point ABI `lto.tmp` objects on riscv64, guard the service-local
  `-flto=thin` cflag with `current_cpu != "riscv64"` just like other explicit
  target-local ThinLTO bypasses; keep location service features selected.
- When `communication/netstack/libhttp_client.z.so` links JS NAPI
  `request_context.cpp`/`http_request_options.cpp` into the native
  `http_client` innerkit and reports unresolved `OHOS::NetStack::Http::*`
  symbols, remove those JS sources from the native BUILD closure and import
  only the target-evidenced native secure/TLS/cache text closure plus required
  deps, including the matching `ability_base` entry in netstack `bundle.json`;
  add only minimal target-evidenced request/response accessors needed by that
  cache closure, and do not disable netstack or fake these namespace-mismatched
  C++ symbols.
- For graphic_3d Lume static-plugin RISC-V blockers, when
  `static_plugin_decl.h` expands `DEFINE_STATIC_PLUGIN` with an undefined
  `SECTION(...)` branch and reports `expected ')'`, apply only the
  target-evidenced `__riscv` section macro branch instead of importing broader
  graphic_3d source changes.
- For SmartPerf split blockers, when target evidence shows SmartPerf is owned by
  `developtools/smartperf_host`, remove legacy `developtools/profiler/host/smartperf`
  labels from the hiprofiler bundle registry to avoid duplicate fuzz outputs.
- For profiler native-daemon/native-hook RISC-V blockers, when
  `register.h` reports `NOT SUPPORT ARCH`, import the target-evidenced
  `register.h`, `register.cpp`, and `call_stack.cpp` support set so RISC-V
  register enums, `buildArchType`, libunwind mapping, and `DfxRegsRiscv64`
  selection are present without disabling profiler features.
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
  compile-only fake interfaces; shared libraries use linkable ELF stubs instead
  of text placeholders.
- When imported vendor/board/SoC targets fail compile-standard part/subsystem
  checks, merge only matching target-evidenced
  `build/compile_standard_whitelist.json` entries in the target product, board,
  and SoC label spaces; do not change product component selection to hide the
  targets.
- For vendor product modules directly listed by `vendor/<vendor>/<product>/ohos.build`,
  import text/config closures such as image config, preinstall config, HDF `.hcs`,
  XML, JSON, `.para`, GN/GNI, and C/header files; represent non-text payloads as
  tracked compile-only fake interfaces, with `.so` payloads generated as
  target-architecture linkable stubs when needed.
- In every base patch manifest, group fake interfaces into a dependency-debt
  summary covering kernel/BSP, boot firmware, kernel modules, SoC proprietary
  payloads, WebView/prebuilt apps, Rust/toolchain, fake component registries, and
  other compile-only fakes. Treat fake component registries as review debt: if
  real source/bundle evidence exists, replace the fake before completion claims.
- Keep host/prebuilt tool failures separate from fake dependency debt. For
  `compile_app.py` app packaging, resolve `ohpm` from the OpenHarmony source
  root with an absolute `get_root_dir()` before changing into app module
  directories; do not fake missing OpenHarmony command-line tools when the real
  workspace prebuilt is available.
- After build attempts, run lightweight regression checks for ABI/LTO/Rust fixes:
  use `llvm-readelf -h` on generated fake shared libraries, scan fake Rust
  archives for non-RISC-V objects, and confirm the build logs no longer contain
  prior blockers such as the rvbook bluetooth whitelist mismatch.
- For ArkCompiler static_core RISC-V runtime failures, import only the
  target-evidenced minimal runtime support needed for compile progress:
  RISC-V `Arch`/`ArchTraits` mapping, runtime/fiber/signal context mappings,
  RISC-V runtime assembly sources, `THREAD_REG`/`MAKE_ASM_NAME` assembly macro
  support, and guarded object accessor overloads. Keep this as source
  compatibility work, not product feature filtering. When
  `cross_values_generator.rb` fails because no arch-name is passed, add only the
  target-evidenced `cross_values/BUILD.gn` `current_cpu == "riscv64"` ->
  `RISCV64` mapping; do not import broader ArkCompiler 6.1 rename churn.
- When ArkCompiler RISC-V bridge assembly reports tp-relative offsets outside
  the signed 12-bit immediate range, classify it as source/build compatibility
  debt and apply a target-scoped ManagedThread large-offset load/store helper
  in the affected RISC-V assembly sources, not in headers also included by C++;
  do not hide it by removing
  ArkCompiler runtime targets or by fake binary substitution.
- For ArkCompiler RISC-V runtime C++ blockers, prefer target-evidenced minimal
  guards such as `string_index_of.h` accepting `PANDA_TARGET_RISCV64` as
  little-endian and `EtsToStringCache` narrowing the lock-free atomic assertion;
  avoid importing broader 6.1 runtime rename churn during compile triage.
- For RISC-V graphics builds, add target-evidenced `graphic_3d` rofs `rv64`
  object mappings to compile files when GN reports empty generated asset paths;
  this is a build-compatibility source fix, not a product feature removal.
- When `graphic_3d` Lume rofs actions emit `rofs_rv64.o` but
  `CompilerAsset.sh`/`LumeAssetCompiler` reports `Invalid argument!`, import
  only the target-evidenced text compatibility needed for riscv64 asset
  generation: `lume_config.gni` cpu-type mapping, `-riscv64` platform parsing,
  and `EM_RISCV64` ELF output support. Ensure the Lume host asset-compiler
  action declares its CMake/C++ source files as inputs; if an existing
  generated `out/<product>/gen/.../LumeAssetCompiler` binary lacks `-riscv64`,
  remove that generated directory before rebuilding so Ninja cannot reuse stale
  host tooling.
- When a RISC-V `graphic_3d` Lume shared library such as
  `libPluginAGP3DText.z.so` fails with mixed floating-point ABI and the response
  file starts with a generated `*_rv64.o` rofs object, set the generated RISC-V
  ELF header flags to `EF_RISCV_RVC | EF_RISCV_FLOAT_ABI_DOUBLE` in
  `LumeAssetCompiler` and remove stale generated `*_rv64.o` outputs before
  rerunning.
- For RISC-V resource object generation, add target-evidenced
  `build/scripts/run_objcopy.py` `riscv64` output/BFD mappings when Ninja
  reports `KeyError: 'riscv64'` from `run_objcopy.py`.
- Apply the same target-evidenced `riscv64` output/BFD mappings to local
  subsystem helpers such as `foundation/arkui/ace_engine/build/tools/run_objcopy.py`
  when their resource-object actions report `KeyError: 'riscv64'`.
- When RISC-V `third_party/libunwind` compilation reports missing
  `src/riscv/Los-linux.c`, compare the target reference `BUILD.gn` and the
  `libunwind-1.8.1.tar.gz` archive. If the archive lacks that file and the
  target reference removed it from RISC-V source lists, apply that text-only
  build compatibility patch instead of generating a fake C source.
- When FFRT public headers report `unsupported architecture` from
  `foundation/resourceschedule/ffrt/interfaces/kits/c/type_def.h` and
  `ffrt_fiber_storage_size` is undeclared, add only the target-evidenced
  `__riscv` fiber storage-size branch (`64`) unless a later build error proves
  broader FFRT API migration is required.
- When FFRT coroutine compilation reports undeclared `STACK_MAGIC`, add the
  target-evidenced `__riscv && __riscv_xlen == 64` branch in
  `foundation/resourceschedule/ffrt/include/eu/co_routine.h`.
- When FFRT sched code reports `Unsupported architecture` from
  `foundation/resourceschedule/ffrt/src/sched/task_client_adapter.h` and
  `CTC_QUERY_INTERVAL` is undeclared, add only the target-evidenced RISC-V
  architecture guard for the existing runtime CTC query path.
- When `cj_environment.cpp` reports `unsupported platform` on RISC-V, add the
  target-evidenced `APP_USE_RISCV64` GN define and the matching
  `APP_LIB_NAME "riscv64"` source branch; do not import unrelated host/macOS
  dynamic-loader changes unless they become build blockers.
- When TEE `teecd` agent C sources fail on RISC-V with unrecognized ARM barrier
  mnemonics such as `isb` or `dsb sy`, add only the target-evidenced
  aarch64/riscv guard around the existing barrier blocks in
  `secfile_load_agent.c`, `fs_work_agent.c`, and `misc_work_agent.c`, using
  `fence.i` and `fence iorw, iorw` for the RISC-V branch.
- When the riscv64 musl `libc.so` link reports mixed floating-point ABI objects,
  align both musl `build/config/components/musl/BUILD.gn` compile/link cflags
  and `third_party/musl/musl_template.gni` hook LTO cflags, plus
  `build/config/compiler/BUILD.gn` riscv64 compiler/linker flags, with the
  target-evidenced `-march=rv64imafdc`/`-mabi=lp64d` ABI. If the response file,
  CRT objects, and linked archives are already `lp64d` but LLD still emits
  mixed-ABI `lto.tmp` objects, use the existing `musl_use_flto` knob in
  `third_party/musl/BUILD.gn` to disable riscv64 shared-musl LTO as a
  compile-only compatibility bridge instead of removing musl or target
  libraries.
- When many riscv64 links fail from `lto.tmp` or `thinlto-cache` mixed
  floating-point ABI objects after musl itself links, disable the default
  riscv64 ThinLTO path in `build/config/compiler/compiler.gni` for the
  OpenHarmony 6.0 clang/lld stack. This is an optimization off-ramp, not a
  product-feature removal.
- If `location/location/liblocator_sdk.z.so` still reports mixed ABI `lto.tmp`
  objects after the global off-ramp, check
  `base/location/frameworks/native/locator_sdk/BUILD.gn` for a target-local
  `-flto=thin` cflag and guard that explicit optimization with
  `current_cpu != "riscv64"` instead of disabling the location component.
- If `arkcompiler/ets_runtime/libark_jsruntime.so` still links with
  `-flto=thin` after the global off-ramp because `arkcompiler/ets_runtime/BUILD.gn`
  injects ThinLTO directly, guard that explicit block for riscv64 instead of
  disabling Ark JS runtime or removing product features.
- When `libark_jsruntime.so` then reports `undefined symbol: LazyDeoptEntry`,
  import the target-evidenced RISC-V `ecmascript/trampoline/riscv64/raw_asm_stub.S`
  and add only the matching `current_cpu == "riscv64"` `ecma_source` branch.
- When Skia `SkRasterPipeline_opts.h` fails on riscv64 because `asin_()` indexes
  a scalar fallback as a vector, apply the target-evidenced non-x86 scalar
  `std::sqrt(1.0f - x)` fallback instead of disabling CanvasKit/Skia.
- For riscv64 Rust failures where `rustc_wrapper.py` ends up invoking host
  `cc` with `--target=riscv64-linux-ohos` or `-mabi=lp64d`, import the
  target-evidenced `build/rust/rustc_toolchain.gni` and
  `build/toolchain/ohos/BUILD.gn` Rust tuple mapping. If the real
  `prebuilts/rustc-riscv` compiler is missing, use an executable compile-only
  fake Rust driver that emits placeholder RISC-V ELF outputs, exports
  discovered `#[no_mangle] extern fn` symbols, and record it as dependency
  debt.
- If that fake Rust driver causes the host `cxxbridge` executable to produce
  empty `wrapper.rs.h/.cc` files, keep the failure classified as Rust/toolchain
  dependency debt and use a compile-only generated bridge header as a temporary
  fake interface; do not delete request/Rust components to hide the missing
  toolchain.
- If `rust_template.gni` reports GN "Assignment had no effect" on
  `crate_type = _crate_type`, check for stale riscv64 guards that stop forwarding
  Rust `sources` or `rustflags`; restore the target-evidenced template forwarding
  before adding new fake interfaces.
- If a riscv64 link fails because a `librust_*.a` archive contains rcgu objects
  that are incompatible with `elf64lriscv`, classify it as stale or host-built
  Rust output. Remove the wrong-architecture archive before rebuilding so the
  real `rustc-riscv` or compile-only fake driver regenerates a RISC-V archive.
- If `hb` reports `FileNotFoundError` for `out/<product>/error.log` from
  `LogUtil.analyze_build_error` after Ninja returns nonzero, classify it as
  build-log infrastructure masking rather than a source porting blocker. Rerun
  after checking for concurrent/interrupted builds, and only patch hb log
  collection if the masking repeats.
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
  product build. Scope validated include/library paths to the linux `clang_x64`
  host toolchain through `extra_cxxflags`/`extra_ldflags`; `LIBRARY_PATH` may be
  exported after validation for host `-static-libstdc++` repair. Record this as
  a host/prebuilt toolchain fix, not fake dependency debt or target-source work.
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
