# MusePaper2 OH6.1 RISC-V First-Run Lessons

Use this reference when continuing the MusePaper2 OH6.1 port, preparing a
similar OH6.x RISC-V version-upgrade port, updating this skill from iteration
records, or deciding whether a runtime symptom is a porting blocker or test
evidence debt.

This is a compact ledger from the first MusePaper2 OH6.1 run through iteration
330. Open the cited iteration records only when implementing an adjacent fix or
when a later result conflicts with the summary here.

## Contents

- [Mission Guardrails](#mission-guardrails)
- [Evidence Chain](#evidence-chain)
- [Build And Source Lessons](#build-and-source-lessons)
- [Package And Image Freshness](#package-and-image-freshness)
- [Device Automation And Recovery](#device-automation-and-recovery)
- [Runtime Triage Rules](#runtime-triage-rules)
- [Subsystem Lessons](#subsystem-lessons)
- [XTS And ACTS Lessons](#xts-and-acts-lessons)
- [HATS Execution Lessons](#hats-execution-lessons)
- [Review Cadence](#review-cadence)

## Mission Guardrails

- Keep the original migration model visible: old completed OH6.0 RISC-V port
  plus clean OH6.1 baseline produces an OH6.1 RISC-V MusePaper2 product.
- Preserve product features by default. Do not remove product components,
  drivers, HDF services, WebView, ArkUI, audio, camera, Wi-Fi, Bluetooth, or
  power features merely to reduce build or test failures.
- Treat full `build.sh` success as a source milestone, not a runtime verdict.
  A candidate still needs packaging, flashing, strict HDC reconnect, smoke,
  screenshot or display evidence, boot params, and known-issue records.
- When the user asks for `rc0`, freeze a testable candidate once boot, recovery,
  UI, core apps, and representative L2/L3 smoke are credible. Do not widen into
  full XTS/HATS/ACTS closure unless the user makes it the release gate.

## Evidence Chain

For image-affecting changes, require the full chain:

1. `./build.sh --product-name musepaper2@spacemit --ccache --prebuilt-sdk`.
2. `build/gen_zip_musepaper2.sh musepaper2`.
3. Linux zip size and SHA256.
4. Windows staging at
   `F:\images\PortingTest\6.1\openharmony-spacemit-k1-musepaper2.zip`, or a
   recorded oh-auto artifact id when direct path use is not allowed.
5. oh-auto `profile musepaper2`, `preflight --template-id musepaper2-titan`,
   and explicit burn-mode evidence when entering fastboot out of band.
6. Flash job `succeeded` with `titan_fastboot_found` and `titan_flash`
   return code 0.
7. Independent `wait-connected` using USB target `0123456789ABCDEF`.
8. Strict `smoke --wait-connected --set-boot-escape-ack`.
9. Boot params, screenshot or `snapshot_display`, and critical dmesg grep.
10. Iteration record and relevant source/skill/work-record commit anchors.

Do not substitute local return codes for evidence. HDC can report process
success while stdout contains `ExecuteCommand need connect-key`, Offline
targets, or no useful payload.

## Build And Source Lessons

- Use four-tree analysis to separate old porting intent, upstream OH6.1 churn,
  and current workspace drift. Do not replay old hunks blindly.
- Use text/source imports for board, SoC, product, GN/GNI, HCS, JSON, XML, and
  C/C++ closures. Use marked compile-only fakes only for missing binary,
  firmware, prebuilt, kernel-module, or toolchain payloads, and keep dependency
  debt visible.
- RISC-V build failures cluster around `target_cpu == "riscv64"` branches,
  LP64D ABI flags, ThinLTO, Rust target tuples/toolchains, Ark/ETS/ArkUI
  runtime bridges, WebView, Lume/resource objects, HDF metadata, and host
  clang/GCC routing. Fix the first real failure and rerun the required entry.
- If an HDF service loads on 64-bit ARM but fails on RISC-V64, inspect hard-coded
  64-bit guards. MusePaper2 audio needed `__riscv && __riscv_xlen == 64` in
  the HDF library path helper so vendor libraries load from `/vendor/lib64`.
- If passthrough HDI factories are missing from a vendor library, check
  `shlib_type = "hdi"` and version scripts. Input needed an explicit map and
  default-visibility factory export before passthrough HATS could load it.
- If an OH6.1 HDF test crashes because a service is missing, confirm the service
  is registered in product HCS. USB device/port HDI services were built and
  packaged but needed `device_info.hcs` registration.
- Hardware may lack sysfs fields that tests assume. Battery HDI should return
  sane non-negative values for missing energy nodes and preserve real charger
  current writes while mirroring HATS-created mock files when present.
- Missing optional product profiles should not be papered over with fake
  product config. BMS extension profile absence was handled by caching the
  fallback state because no real MusePaper2 extension profile or implementation
  existed in either old or new evidence.
- Permission-profile failures can block preinstalled HAP registration even when
  the HAP exists in the package. MediaLibraryData required adding
  `ohos.permission.MANAGE_CRITICAL_PHOTOS` to the signed profile ACL and
  verifying both profile and HAP before full build/package/flash.

## Package And Image Freshness

- Kernel, KHDF, DTS, and vendor init edits are especially prone to stale image
  validation. Check `out/kernel/OBJ`, `Image`, `bootfs/Image.itb`, `boot.img`,
  and the zip hash or timestamp after such changes.
- GN kernel actions only rebuild for declared `inputs`. Vibrator KHDF preset
  edits were not picked up until MusePaper2 KHDF HCS files were added to the
  kernel action inputs.
- Audit packaged inputs when a runtime result contradicts a source change:
  HAPs, profiles, `product_musepaper2.para`, HDF HCS/HCB, helpers installed in
  `/system/bin`, CA wrapper paths, vendor libraries, and boot-image strings.
- For Camera, keep the standard product path as the rc0 path:
  `./build.sh --product-name musepaper2@spacemit --ccache --prebuilt-sdk`.
  A tablet device-type build fixed one preinstall visibility issue but selected
  a bad Camera runtime/layout path.

## Device Automation And Recovery

- Use oh-auto for HDC, UART, Titan flashing, screenshots, pushes, pulls,
  bugreports, and Windows staging. Do not use local Linux HDC or flasher
  commands for the MusePaper2 rig.
- Query `oh_autoctl.py profile musepaper2` before a new device loop. Treat it
  as the source of truth for Titan template, USB target, UART, baudrates, and
  current rc0 artifact/hash.
- `preflight ok=true` means flash submission readiness, not proof that the
  board is in Titan burn mode. Use `wait-titan-fastboot` after `reboot fastboot`
  when explicit burn-mode evidence is needed; in-job `titan_fastboot_found`
  remains authoritative.
- MusePaper2 can enter Titan mode with `reboot fastboot` from HDC or serial.
  Use HDC when OpenHarmony is alive; use serial when HDC is unavailable but the
  console responds.
- Use COM4 at 115200 for serial console and `serial-log`. Do not reuse the HDC
  UART baudrate 921600 for boot logs unless a fresh probe proves it.
- Keep boot escape strict for panic-prone images:
  `timeout_sec=60`, `accept_boot_completed=false`, `ack=false`. For rc0/test
  builds that already reach boot completed, relax to `timeout_sec=120` and
  `accept_boot_completed=true`.
- Set `startup.porting.boot_escape.ack=true` only after HDC or serial command
  access is verified. A UI screenshot alone is not a recovery guarantee.
- If a board panic-stops before command access and no reset relay exists,
  persist image hash, flash job, serial excerpt, and reason, then notify the
  operator for manual reset.

## Runtime Triage Rules

- Triage in this order: recovery command access, boot params, screenshot/UI,
  service registration, user-visible functions, then log noise.
- Allow boot to settle before failing `bootevent.boot.completed`. Early post
  reboot probes can see HDC, launcher, services, and later boot completed.
- A black screenshot is not automatically a display failure. Check screen
  sleep, wake/unlock state, lock-screen focus, camera permission dialogs, and
  scene lighting before editing source.
- Do not classify native OpenHarmony log noise as a porting blocker without a
  correlated functional failure, crash, panic, service death, restart storm, or
  missing device node.
- Repeated I2C timeout dumps, App/NWeb/XCollie watchdog kick logs, optional
  SoftBus plugin absence, SAMGR idle unloads, metadata warnings, and BMS
  fallback messages are detail debt when boot/UI/HDC/core services pass.
- Inspect stdout for every automation job. A successful job with truncated
  stdout, missing sample markers, `[Empty]`, `Offline`, or `need connect-key`
  is incomplete evidence.
- For stability probes, prefer compact repeated shell jobs or device-side files
  pulled as artifacts. Long HDC shell loops can finish as `succeeded` while the
  captured stdout is truncated.

## Subsystem Lessons

### Camera, Media, Photos

- After granting Camera permissions, force-stop and cold-start Camera before
  judging preview. A hot-start can show UI while CameraService reports zero
  active sessions.
- Positive Camera rc0 evidence needs at least one active camera/session, repeat
  stream, no critical kernel error, and capture evidence if photo flow is in
  scope.
- For MusePaper2's 1200x1920 permission dialog, the Allow button is around
  `745 1045`. For the Camera shutter, use a precise center around `600 1710`.
- Do not overreact to dark preview when the device is in a dark room. Recheck
  under daylight or with a controlled light source before changing camera code.
- Validate Camera -> MediaLibrary -> Photos as a full user path: capture log,
  generated media files under `/storage/media` or `/storage/cloud`, and Photos
  thumbnail display.
- If Photos or FilePicker fails through DataShare, verify the real bundle and
  ability names from `bm dump`, then check MediaLibraryData registration and
  signed profile ACLs before changing application code.

### Wi-Fi And Network

- Treat SSIDs as case-sensitive. The working lab SSID observed in this run is
  `ISRC-Wifi`; lower-case `isrc-wifi` produced false connection failures.
- Do not persist PSKs in iteration records. Prefer redacted service helpers;
  after manual credential probes, clear hilog and run a plaintext secret scan
  before committing records.
- Use `network_smoke_ok`, gateway ping, external ping, DNS/HTTP, and
  `route_default_observation` together. A missing legacy default route is not a
  failure when OpenHarmony networking still reaches gateway and external hosts.
- If Framework scan/config APIs fail from HDC permission limits, fall back to a
  system diagnostic helper using `wpa_cli` status and scan. If the AP is absent
  from low-level scan results, classify the result as environment-dependent,
  not a proved port regression.
- For HTTPS, distinguish network failure from CA path failure. MusePaper2 uses
  CA aliases and a small curl wrapper so default `curl -I https://...` succeeds.

### Bluetooth

- The default disabled state is not a bring-up failure. Verify service,
  capabilities, rfkill, and HCI plumbing first.
- Do not equate direct rfkill writes or vendor RF tools with OpenHarmony
  framework enable/disable behavior.
- A small diagnostic helper can validate framework enable/disable. Use the same
  API semantics as Settings: enable BLE/BT path and disable full BT, then
  confirm `BluetoothHost -br` and rfkill state.
- Do not claim pairing, scan, A2DP, HID, or interoperability without a known
  peer fixture. Record them as open test-team scope.

### Audio

- If AudioPolicy reports zero local devices while ALSA nodes exist, first check
  HDF vendor library load paths and whether vendor impls are mapped in
  `audio_host`.
- `aplay` returning `Resource busy` during a normal OpenHarmony boot can be
  expected because `audio_server` owns the PCM. Validate app-layer playback or
  run direct-HDI tests under a controlled service state instead.
- Music Demo playback is stronger rc0 evidence than raw ALSA: launch the real
  ability, accept permission, press play, verify UI progress, renderer state,
  and non-silent audio logs.
- For direct Audio HDI HATS, stale service ownership can create false
  `CreateRender` failures. Stop `audio_server`, restart `audio_host`, run the
  direct-HDI binary, then restart `audio_server` when that mode is needed.
- The same rule applies to formal xDevice Audio HDF modules on MusePaper2:
  Manager and Effect modules can pass as plain xDevice, but Adapter/Render/
  Capture direct-HDI modules should be run under the controlled
  `audio_server` stopped and `audio_host` restarted precondition, with
  `audio_server` restored and oh-auto smoke checked after the batch.
- `HatsHdfAudioIdlCaptureAdditionalTest` needs a longer xDevice native test
  timeout. Use a staged `--native-test-timeout-ms 600000` patch; do not edit
  the source `Test.json` just to change a local probe timeout.
- For aggregate Audio HDF HATS, use clean boots and long timeouts. Rerun
  failed filters from a clean state before editing product audio code.

### Power, Battery, Thermal, RTC

- Battery/thermal service visibility is not enough; HATS can reveal missing
  energy-node or readback assumptions. Preserve real charger sysfs behavior
  while providing sane values for missing optional fields.
- Screen power-key sleep/wake is a useful remote smoke before deeper suspend.
  Kernel deep suspend/resume, charger plug/unplug, and power consumption need a
  fixture or operator plan.
- If the lock screen date looks stale, verify and sync RTC before blaming OH6.1
  source. Confirm `date`, `/proc/driver/rtc`, reboot persistence, and boot
  completed after sync.

### Input, USB, Sensor, Light, Vibrator

- Input and USB HATS failures can be product HCS/export issues rather than core
  framework failures. Check service registration, factory exports, and version
  scripts before changing high-level input or USB behavior.
- Sensor service can be considered healthy when service/additional HATS pass
  and samples show real values, but physical value-change coverage still needs
  motion/light/proximity fixtures.
- Light and vibrator HATS include long timing cases. Use sufficient per-binary
  timeout and do not call a short-timeout run a product failure.
- Run native HATS from a writable directory under `/data/local/tmp`. Some gtest
  binaries try to write XML in the current directory and can exit fatally after
  all cases pass if executed from `/`.
- For vibrator preset fixes, keep UHDF and KHDF HCS aligned and prove the
  presets landed in `boot.img`, not just in userspace HCB.

## XTS And ACTS Lessons

- For OH6.1 XTS builds, put `prebuilts/python/linux-x86/3.11.4/bin` before the
  host Python. The ACTS/HATS helper scripts use Python 3.10+ type syntax.
- For ACTS on MusePaper2 RISC-V64, keep fixes additive and coverage-preserving:
  add the missing `target_cpu == "riscv64"` branch for
  `commonlibrary/toolchain` `tar_dllib`, add `riscv64-linux-ohos` in
  `build/ohos_var.gni`, add dEQP riscv64 target macros in `vk_gl_cts.gni`, and
  route multimedia AV codec 64-bit library paths to `/system/lib64`.
- ACTS generated a nested suite root: use
  `out/musepaper2/suites/acts/acts` for xDevice ACTS, not the outer
  `out/musepaper2/suites/acts` directory.
- Do not upload the full ACTS suite for first probes. The MusePaper2 ACTS
  output was about 9.5 GB. Use `oh_xts_xdevice_runner.py --stage-module-only`
  for single-module xDevice checks; it stages only config/tools/run scripts and
  testcase files referenced by the selected module JSON.
- `ActsStartupSysDeviceInfoTest` is a good low-risk ACTS smoke on MusePaper2:
  the first source-built ACTS probe passed 85/85. `ActsHilogNdkTest` completed
  the xDevice flow but had hilog assertion failures, so classify it as
  subsystem follow-up rather than runner bring-up failure.
- If an ACTS native HAP fails on RISC-V while the module runs on other ABIs,
  inspect the HAP for `libs/riscv64/*` before debugging the subsystem. For
  `ActsHilogNdkTest`, the missing RISC-V assistant HAP library caused 11 hilog
  assertion failures; after adding `riscv64` to the HAP build profile and
  completing the RISC-V NDK SDK layout, the module passed 64/64 through
  xDevice.
- OH6.1 RISC-V NDK HAP builds may require a complete SDK shape, not only a
  target-cpu GN branch: Hvigor ABI enum/schema support, CMake
  `OHOS_ARCH=riscv64`, sysroot startup files and architecture headers from
  OH musl, compiler-rt crt/builtins, `libunwind.a`, and NDK libc++ with the
  same `std::__n1` ABI as `libc++_shared.so`. Do not mix the LLVM
  `std::__h` libc++ into HAP builds that compile against `std::__n1` headers.
- ACTS-Validator can build into `out/musepaper2/suites/acts/acts-validator`,
  but the first xDevice smoke reported `unavailable=1` because
  `testcases/queryStandard` and related validator resources were missing. Treat
  that as an incomplete package/resource issue before investigating product
  behavior.
- DCTS can be source-built for MusePaper2 RISC-V64 with the same prebuilt
  Python PATH pattern. It generated `out/musepaper2/suites/dcts` in the first
  probe. A single-module smoke of `DctsFileioClientTest` proved xDevice launch
  but failed 121/121 cases, which is expected until a distributed/two-device
  topology is available.
- DCTS/Hvigor builds may leave generated `oh-package-lock.json5`, `.hvigor/`,
  `build/`, `oh_modules/`, `local.properties`, and modified `hvigorw` files in
  `test/xts/dcts`. Treat them as build byproducts unless a targeted diff proves
  otherwise.
- As of the first OH6.1 XTS closure pass, the official XTS page had no
  OpenHarmony 6.1 Release standard-system resource download. Record this as a
  resource gap and do not mix OH6.0 arm32 resources into OH6.1 RISC-V formal
  evidence.
- External SSTS packages may ship stale xDevice packages even when their
  testcase/resource structure is valid. The 2026-06-15 SSTS package carried an
  xDevice `2.30.0.1104` base that failed with missing `pkg_resources` and then
  `cannot import name 'CaseEnd'`. Use
  `oh_xts_xdevice_runner.py --tools-dir out/musepaper2/suites/acts/acts/tools`
  to run SSTS content with the source-built xDevice 5.0.6.100 tool bundle.
- For Windows Python 3.12 xDevice runs, uninstall stale `xdevice*` packages
  before each suite tool install and force `setuptools<81`; otherwise legacy
  suites that import `pkg_resources` can fail before reaching the device.
- Source-built suites may include both underscore and hyphen spellings of the
  same xDevice package, for example `xdevice_devicetest-0.0.0.tar.gz` and
  `xdevice-devicetest-0.0.0.tar.gz`. Normalize names and install only one copy
  per package, otherwise pip can fail with `ResolutionImpossible` before the
  test reaches the device.
- xDevice XML may set `status="disable"` and `result="false"` for cases that
  were not actually run after an earlier failure. Treat `status=disable`,
  `status=disabled`, `status=blocked`, or `message="...mark blocked..."` as
  blocked before counting `result=false` as a real failure. In iteration342,
  `ActsArrayTest` was correctly reduced to one stable failed case
  `ArrayCombinationTest4158` and 3357 blocked cases after fixing the parser and
  rerunning the module.
- For ACTS OHJSUnit/Hypium sequence triage, validate passing subsets as well as
  failing windows. In iteration349-350, `ArrayCombinationTest4158` passed alone,
  passed paired with `4153`, and passed in all tested five-case subsets, while
  the full `4153-4158` six-case window failed repeatedly at `4158`. Treat this
  as a higher-order sequence/state/resource interaction before changing product
  runtime code or weakening the test.
- A stable OHJSUnit failure after a long previous case can be AppFreeze rather
  than JS semantics. In iteration353, `ActsArrayTest` `4153-4158` failed at
  `4158` because `4157` ran for about 8s and the next CPU-heavy case hit
  `APP_FREEZE` / `THREAD_BLOCK_6S`; direct `aa test` passed when
  `hiviewdfx.appfreeze.filter_bundle_name=com.acts.test.arraytest` was held.
  Use that parameter only as a diagnostic A/B probe. It was unreliable as an
  xDevice formal workaround because dryRun/install/runner lifecycle can race
  with parameter changes.
- The durable fix for the same ACTS AppFreeze pattern was product-side and
  tightly scoped: in developer mode, skip appfreeze killing for `com.acts.*`
  test bundles while preserving ordinary app watchdog behavior. After flashing
  the fixed image, xDevice `ActsArrayTest` `4153-4158` passed 6/6 without the
  dynamic filter parameter; `4157` took 8.022s and `4158` took 4.755s.
- Keep xDevice result counting tied to `summary/test_summary.yaml` and XML, not
  ad hoc wrapper fields. In iteration344 an external TSV helper initially read a
  nonexistent `totals` key and printed zero cases even though the module
  summaries and XML reported real pass counts; regenerate derived summaries from
  `runner_summary` or `xml_summary.counts`.
- When xDevice report collection indexes Windows-side `.gz` hilog or kmsg
  artifacts, pull them as bytes rather than text before classifying an ACTS
  failure. `collect_reports.py --pull-text-from-runner` now preserves small
  `.gz` files through PowerShell `ReadAllBytes` plus base64; validate with
  `gzip -t` when the compressed log is central evidence.
- For ACTS expansion, inspect each module JSON before classifying it as
  low-risk. AppInstallKit-only pure JS modules such as `ActsDateTest`,
  `ActsRegExpTest`, `ActsSymbol1Test`, `ActsSymbol2Test`, `ActsMapTest`, and
  `ActsProxyTest` passed in iteration343. A JS-looking module can still carry
  `ShellKit` or system-state commands; `ActsJsonJSApiTest` includes
  `power-shell wakeup` and `power-shell setmode 602`, so it was deferred from
  the low-risk batch.
- A module that stages and returns from xDevice can still expose a real ACTS
  partial failure. Do not assume the first observed failed case is stable:
  `ActsObjectTest` first reported `Object1Test036`, but immediate reruns moved
  the first failed case to `Object1Test037` and `Object1Test041` after earlier
  cases passed. Classify this as suspected runner/app early termination or
  flake until rerun evidence stabilizes; only then spend source-debug effort on
  a fixed Ark/ETS semantics assertion.
- Iteration355 narrowed `ActsObjectTest` further. `Object1Test052` passed as a
  single filtered case, the `Object1Test049-052` window passed, and the whole
  `Object1Test` class passed 92/92 through `-ta class:Object1Test`. This
  weakens the earlier theory that the first full-module failure was a stable
  Object1 semantic defect. Some `ActsObjectTest` describe names are not
  directly runnable through `-ta class:` even though they are listed by the full
  module: `Object33Test` dryRun collected zero tests and reported the module
  unavailable. Treat zero-collection class filters as filter/runner limitations
  until a clean full-module or source-level mapping proves a product failure.
  If a manual power dialog or sidecar HDC probe overlapped the run, discard it
  as contaminated evidence.
- The first SSTS smoke reached OHYaraTest with `OpenHarmony-SA-2025-11` and
  produced `blocked=1`, not a runner failure. The block came from security patch
  `2026-02` being four months behind current month `2026-06`, exceeding the
  SSTS two-month patch-label policy.

## HATS Execution Lessons

- Build HATS with the repo prebuilt Python 3.11 and `test/xts/hats/build.py`;
  host Python 3.8 is not a reliable OH6.1 HATS runner.
- Use `oh_hats_native_runner.py` for upload, push, chmod, run, XML pull, and
  JSON/TSV summaries. Do not hand-roll the same sequence for every binary.
- For formal xDevice evidence, use the generated suite root under
  `out/musepaper2/suites/hats` and run from the Windows workbench because the
  MusePaper2 HDC target is visible there. The first formal probe staged that
  suite under `F:\images\PortingTest\6.1`, installed the suite xDevice packages
  with the oh-auto Python 3.12 runtime, and passed `HatsGetcwdTest` through
  xDevice with one test passed and zero failed.
- Broad low-risk HATS xDevice expansion can proceed in small independent
  batches. By iteration346, syscall/memory/scheduler/file modules and
  Light/Vibrator/Sensor/Input HDF modules reached 88/99 HATS modules passed
  with 15574 cases passed. Keep the remaining HATS modules grouped by risk:
  Audio HDF, Power/Battery/Thermal, DMA/Display/USB, and Startup partition slot
  should not be mixed into the same unattended batch.
- By iteration347, the Audio HDF group was closed through formal xDevice using
  the direct-HDI isolation rule and one staged long-timeout patch: 9 modules,
  861 total cases, 860 passed, 1 ignored/skipped, 0 failed. The remaining HATS
  list by iteration346 delta is Power/Battery/Thermal, DMA, Display, USB auto
  function, and Startup partition slot.
- By iteration348, the non-Audio HATS remaining group was almost closed through
  formal xDevice: DMA buffer, Display buffer UT, USB auto function, Power,
  Battery, and Thermal modules passed with 232 total cases, 230 passed, 2
  ignored/skipped, and 0 failed.
- `HatsStartupPartitionSlotTest` is a safety-gated exception. It calls
  `SetActiveSlot` and `SetSlotUnbootable` for slots 0-3. On MusePaper2, a
  read-only probe showed `slots=2,current=0`, and suffix probes were not
  intuitive enough to trust unattended mutation. Do not run this full module
  until a physical recovery backend or dedicated fixture is proven, or run only
  a clearly labeled read-only/filter probe without claiming full pass.
- Do not point `xdevice run -c` at the `config` directory. Use
  `-c .\config\user_config.xml`; `-rp .\name` is reported under the suite's
  `reports` directory.
- Create and chmod remote directories before `push`; then verify with `ls -l`.
  A push job can appear successful when the nested target directory is not ready
  for the subsequent run.
- Delay destructive or topology-changing suites until recovery is strong:
  active-slot changes, suspend, sysctl, mount namespace, network topology,
  USB-role changes, and battery/thermal mutation.
- When a full aggregate produces a small number of failures, rerun failed
  filters and then the involved binaries before changing source. When a second
  immediate aggregate produces broad new failures, suspect state pollution and
  reboot before retesting.

## Review Cadence

- Keep an independent work-record directory with per-iteration evidence,
  image hashes, flash jobs, screenshots, logs, summaries, manual reset notes,
  and source/skill/work-record commits.
- Every 5 to 10 iterations, write a review that checks alignment with the
  original migration goal, identifies evidence gained, names open risk, and
  calls out rabbit holes.
- Useful review questions:
  - Is the work still migrating the old OH6.0 RISC-V port onto OH6.1, or has it
    drifted into unrelated cleanup?
  - Did any source change remove product functionality?
  - Is the latest image buildable through `build.sh`, flashable, bootable, and
    recoverable?
  - Are logs being promoted only when tied to a user-visible or interface-level
    failure?
  - Should the next step be rc0 handoff, fixture-dependent testing, or a
    source fix backed by a reproduced symptom?

Key record anchors:

- `records/rc0/rc0_project_retrospective_zh.md`
- `records/iteration314_rc0_refresh_summary/iteration304_313_review.md`
- `records/iteration330_ten_iteration_review/iteration320_329_review_zh.md`
- `records/rc0/skill_update_summary.md`
- `rc0_candidate_status_20260614.md`
