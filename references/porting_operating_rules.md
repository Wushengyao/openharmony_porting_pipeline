# Porting Operating Rules

Use this reference when making source-affecting porting decisions, interpreting
build failures, using the execution assistant, or deciding whether a workaround
is acceptable. Keep these rules loaded only when needed; `SKILL.md` stays as a
navigation layer.

## Contents

- [Evidence And Stage Discipline](#evidence-and-stage-discipline)
- [Version-Upgrade Discipline](#version-upgrade-discipline)
- [Controlled Apply And Dependency Debt](#controlled-apply-and-dependency-debt)
- [Build-Triage Pattern Index](#build-triage-pattern-index)
- [Runtime And Device Evidence](#runtime-and-device-evidence)
- [Handoff Artifacts](#handoff-artifacts)

## Evidence And Stage Discipline

- Keep stage isolation: pass files and stage results between stages, not full
  chat history.
- Treat repository records, diffs, manifests, binary hashes, dirty workspace
  records, and logs as evidence.
- Keep operator context as user-supplied hints. If it conflicts with repository
  evidence, record the conflict and prefer verifiable evidence.
- Preserve unknowns instead of inventing build, boot, runtime, provenance, or
  validation status.
- Do not promote force-sync SDK commits, initial imports, `.gitattributes`-only
  commits, dirty workspace files, or binary imports into reusable source-fix
  cases.
- Keep `evidence_type` / `evidence_level` separate from `evidence_strength`.
- Build acceptance evidence is compile-flow evidence only. It must not be used
  to claim boot, runtime, driver runtime, app, CTS, or test pass.
- Prefer repository scripts over hand-written ad hoc extraction or validation.
- Use `porting_knowledge_output/` as the default output root unless the user
  specifies another directory.

Read `references/evidence_rules.md` for compact evidence citation rules and
`references/stage_contract.md` for stage result contracts.

## Version-Upgrade Discipline

- Four-tree version-upgrade porting is optional and plan-only by default. It
  must not change the default single-scenario pipeline behavior.
- Use four-tree mode to classify `old-original -> old-ported` as old porting
  intent, `old-original -> new-original` as upstream version churn, and
  `new-original -> new-workspace` as current target-workspace drift.
- Obtain `old-original` from the exact frozen baseline used before the old
  port. Prefer a locked repo manifest inside `old-ported` over downloading a
  moving release branch.
- Migrate intent rather than replaying old hunks. Classify each old-porting
  item as direct review, upstream merge, retarget required, already in
  progress, external dependency follow-up, or unknown.
- Keep four-tree upgrade artifacts under `09_version_upgrade/`; they are
  evidence and work orders, not proof of completed runtime porting.
- Use `implementation_readiness`, `porting_completion_summary`,
  `source_file_blueprint`, `source_candidate_manifest`, `target_source_evidence`,
  `source_import_plan`, and `porting_work_order` to separate reviewable source
  work from vendor/BSP/binary dependencies and incomplete validation states.

## Controlled Apply And Dependency Debt

- Use `apply_porting_base_patch.py` only after target seed and target source
  evidence identify concrete L0/L1 text files. Its default mode stages files
  under the output directory without workspace writes; `--apply` is required
  for source edits and `--attempt-build` is allowed only after apply.
- Keep product and board feature declarations visible where possible. When a
  blocker is caused by a missing binary/prebuilt/third-party payload, prefer a
  clearly marked compile-only fake interface over removing the feature.
- When a missing `.so` participates in target linking, generate a
  target-architecture ELF shared-library stub rather than a text marker file.
  If a reference target `.so` exists, derive compile-only exported symbols from
  its dynamic symbol table and keep the real binary as unresolved runtime debt.
- Treat Python build/generator scripts as text closure inputs. Compile-only
  fake payloads are for binary, prebuilt, firmware, kernel-module, and other
  non-text dependencies.
- When provenance-checked dependencies arrive, record them in
  `real_dependency_inventory.yaml` and pass `--real-dependency-inventory`.
  Preserve matching real files/directories and stop on missing paths,
  fake-marked files, hash mismatch, or ABI mismatch.
- Keep host/prebuilt tool failures separate from fake dependency debt. Do not
  fake OpenHarmony command-line tools when the real workspace prebuilt is
  available.
- Preserve target-evidenced executable bits for directly invoked build scripts.
  Content-identical files may still need a mode-only update.
- In every base patch manifest, group fake interfaces into a dependency-debt
  summary covering kernel/BSP, boot firmware, kernel modules, SoC proprietary
  payloads, WebView/prebuilt apps, Rust/toolchain, fake component registries,
  and other compile-only fakes.

## Build-Triage Pattern Index

For exact historical build-trigger patterns, first search:

```bash
rg -n "the error text or symbol" README.md tools/apply_porting_base_patch.py references
```

The detailed catalog lives in `README.md` and in the pattern detection/actions
inside `tools/apply_porting_base_patch.py`. Use this reference as the routing
index and keep exact source edits evidence-bound.

Common OH6.x RISC-V build-triage clusters:

- NDK/SDK mapping: `riscv64-linux-ohos`, `target_platform_triple`, libc++ and
  curl target branches.
- Musl/ABI/LTO: LP64D flags, `-march=rv64imafdc`, `-mabi=lp64d`, musl
  `musl_use_flto`, global or target-local ThinLTO off-ramps.
- Rust: `rustc-riscv` tuple/toolchain mapping, compile-only fake Rust driver
  when the real prebuilt is absent, stale wrong-architecture archives.
- ArkCompiler/ETS: RISC-V target defines, runtime/fiber/signal mappings,
  assembly macro support, `LazyDeoptEntry`, large-offset bridge assembly,
  minimal little-endian/atomic guards.
- ArkUI/ACE/CJ/NAPI: RISC-V NAPI defines, old-pipeline compatibility closures,
  symbol export maps, and minimal NDK guards.
- WebView/ArkWebCore: keep `web:webview` selected, import text build/glue
  closures, fake prebuilt HAPs only as compile-flow bridges, do not fake
  generated glue sources.
- Graphic/Lume/resource objects: RISC-V rofs object mappings, Lume
  asset-compiler `-riscv64` support, RISC-V ELF flags, objcopy BFD mappings.
- FFRT and runtime headers: narrow `__riscv` branches for fiber storage,
  coroutine stack magic, task client CTC query path.
- HDF/vendor/board/SoC: import text/config closures, represent firmware and
  non-text payloads as compile-only debt, use ELF stubs for linkable `.so`
  payloads, preserve product features.
- Host/prebuilt toolchain: scope validated host GCC include/library fixes to
  host toolchains; avoid global include path contamination of target builds.
- hb/log infrastructure: distinguish log masking or interrupted build state
  from source porting blockers.

When a build failure matches one of these clusters, prefer target-evidenced
minimal source/build compatibility fixes. Do not disable product components,
remove feature flags, or create fake C++ symbols while a real source or
generated-library dependency can be represented.

## Runtime And Device Evidence

- Keep build, flash, boot, and runtime evidence separate. A successful build is
  not a bootable image until packaging, flashing, reconnect, smoke, and logs
  prove it.
- Do not let noisy native OpenHarmony logs become the main objective without
  functional correlation. I2C, battery, thermal, metadata, parameter, or retry
  warnings are detail debt when the device reaches UI, HDC smoke, screenshots,
  and registered core services.
- For local device automation, read `docs/local_device_automation.md` and query
  the service profile before relying on device IDs, serial ports, Windows paths,
  baudrates, or flash templates.
- For MusePaper2-specific runtime lessons, read
  `references/musepaper2_oh61_lessons.md`.
- For formal XTS/HATS/ACTS/DCTS/SSTS, read
  `references/openharmony_xts_formal_workflow.md`.

## Handoff Artifacts

- Treat `porting_completion_summary.md` as the compact handoff after each
  controlled apply/build run. It records build status, patch coverage,
  fake-interface dependency debt, external prebuilt deferrals, and next
  validation work.
- Treat `dependency_request.md` as the external-dependency request list. It
  groups unresolved fake interfaces by dependency category and includes a
  `real_dependencies` inventory template for later vendor/BSP payload intake.
- Use `target_dependency_inventory` to summarize binary, firmware, bootloader,
  prebuilt, and closed-driver candidates without promoting them to source fixes.
- In cross-scenario output, distinguish `universal_by_design` pipeline
  guardrails from `universal_from_evidence` case/pattern-derived methods.
  Generate and validate conditional methods with
  `derivation=conditional_from_evidence` and preserve direct traceability via
  `meta_method_to_case` and `meta_method_to_pattern` rows.
