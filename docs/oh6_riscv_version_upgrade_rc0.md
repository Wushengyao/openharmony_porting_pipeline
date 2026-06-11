# OH6.x RISC-V Version-Upgrade Porting And rc0 Stabilization

Use this runbook when an already completed OpenHarmony RISC-V port must be
migrated onto a newer OH6.x release and the operator wants a test-team `rc0`
before full XTS/HATS/ACTS completion.

The workflow is evidence-first: build success is only a source milestone. A
testable candidate requires `build.sh`, packaging, flashing, HDC/serial
recoverability, boot evidence, screenshots, and a known-issue ledger.

## Contents

- [Inputs](#inputs)
- [Phase Gates](#phase-gates)
- [MusePaper2 Rig Profile](#musepaper2-rig-profile)
- [Boot Escape Policy](#boot-escape-policy)
- [Runtime Triage](#runtime-triage)
- [HATS Native Smoke Pattern](#hats-native-smoke-pattern)
- [Time-Savings Estimate For Future Similar Ports](#time-savings-estimate-for-future-similar-ports)

## Inputs

Required four-tree model:

| Input | Meaning |
|---|---|
| `old-original` | Frozen baseline before the old completed port |
| `old-ported` | Old release after the port was completed |
| `new-original` | Clean newer release before porting |
| `new-workspace` | Newer release workspace to receive the migrated port |

Do not replace `old-original` with a moving branch. If the old clean tree is
missing, reconstruct it from a locked manifest before claiming full upstream
churn analysis. Manifest-only mode is useful but partial.

Create an independent work-record directory before editing source. Keep:

- `records/iteration_log.md`
- per-iteration raw evidence directories
- source import and dependency ledgers
- manual reset or operator intervention records
- image hashes, flash job ids, smoke outputs, screenshots, and summaries

## Phase Gates

### G0: Baseline And Import Gate

Run `run_version_upgrade_porting.sh` with the four trees. Classify old-porting
changes as direct migrate, upstream-merged, retarget-required, external
dependency, or unknown.

Import real BSP/vendor/toolchain dependencies from the old completed port only
after provenance is clear. Keep binary/prebuilt imports visible in a ledger; do
not silently replace missing binaries with guessed files.

### G1: Build Closure Gate

The required acceptance build entry is:

```bash
./build.sh --product-name <product>@<vendor> --ccache --prebuilt-sdk
```

For OH6.x RISC-V ports, expect blockers in:

- `target_cpu == "riscv64"` GN branches
- musl LP64D flags and ThinLTO
- Rust target tuple/toolchain selection
- Ark/ETS/ArkUI runtime and NAPI bridges
- WebView source/prebuilt route
- Lume/Graphic resource-object generation
- HDF part/deps/sanitizer metadata
- host clang/GCC include or static-libstdc++ routing

Fix the first real failure, rerun `build.sh`, and record the first failing
target and the verified next milestone. Do not remove product features to hide
missing dependencies; if a compile-only stub is unavoidable, record the debt and
the real replacement condition.

### G2: Package, Flash, And Recovery-First Gate

After build success, package with the product-specific script and record the
zip path, size, mtime, and SHA256.

For MusePaper2 K1, the current template is:

```bash
build/gen_zip_musepaper2.sh musepaper2
```

Before flashing, verify image freshness:

- `out/kernel/OBJ/...` reflects touched kernel sources when kernel changes were
  made.
- `Image`, `bootfs/Image.itb`, `boot.img`, and the final zip have fresh mtimes
  or changed hashes.
- kernel GN action `inputs` include the files that should trigger rebuild.

The first boot objective is recovery, not a desktop:

- no early kernel panic path before command access;
- HDC or serial can run `reboot fastboot`;
- the next flash cycle can proceed without manual reset.

For the MusePaper2 rig, use `oh_autoctl.py`; do not use local Linux HDC/flasher
commands. Strong flash evidence is `titan_fastboot_found` plus final flash job
`succeeded`, followed by independent `wait-connected` and `smoke`.

### G3: Boot/UI Gate

Treat these as the minimum boot evidence:

- `param get bootevent.boot.completed` is `true`
- launcher, RenderService, WMS, and appfwk readiness are `true`
- USB HDC is connected using the concrete target, e.g. `0123456789ABCDEF`
- a screenshot shows OpenHarmony UI, not the vendor logo
- critical dmesg grep is empty for `Kernel panic`, `not syncing`,
  `sysrq triggered`, `Oops`, and `BUG:`

Do not let noisy native logs become the main objective without functional
correlation. I2C timeout, LoopEvent, AppSpawn kick, metadata, or parameter
warnings are detail debt when the device reaches UI, HDC smoke, and core
services.

### G4: rc0 Freeze Gate

When the user asks for a test-team `rc0`, stop widening XTS/HATS and freeze the
candidate. The rc0 gate is:

- full `build.sh` has succeeded for the candidate source state;
- product zip hash and path are recorded;
- flash job succeeded;
- HDC reconnect and strict smoke succeeded;
- boot params and screenshot prove the UI is up;
- recovery path is still available;
- source commits exist for every change that entered the image path;
- known dirty workspace and untracked generated artifacts are explicitly
  listed;
- known issues and next test layers are documented.

Recommended rc0 record files:

- `records/rc0/rc0_release_note.md`
- `records/rc0/rc0_project_retrospective_zh.md`
- `records/rc0/smoke_probe.json`
- `records/rc0/boot_params_probe.json`
- `records/rc0/preflight.json`
- `records/rc0/status_probe.json`
- `records/rc0/dmesg_critical_grep.json`
- `records/rc0/rc0_current_screen.jpeg`

The rc0 release note should include:

- image path, size, mtime, SHA256, artifact id;
- build and packaging commands;
- source commit anchors by repository;
- push status and credential blockers;
- boot escape policy;
- screenshot and boot/HDC evidence;
- known issues;
- L0-L4 test layering.

### G5: Post-rc0 Test Expansion

After rc0 handoff, continue in layers:

| Layer | Scope |
|---|---|
| L0 | flash, HDC reconnect, boot params, screenshot, critical dmesg grep |
| L1 | Launcher, Settings, Camera preview, basic input, screenshot |
| L2 | Wi-Fi, Bluetooth, Audio, USB, Sensor, Power/Battery/Thermal, RTC, Camera capture/record |
| L3 | representative native HATS/HDF/syscall subsets |
| L4 | formal xdevice HATS/XTS/ACTS reports |

Use native HATS expansion to find regressions, but do not block rc0 on full
XTS/HATS/ACTS unless the user explicitly makes it a release gate.

## MusePaper2 Rig Profile

Current known values:

| Item | Value |
|---|---|
| Titan template | `musepaper2-titan` |
| USB HDC target | `0123456789ABCDEF` |
| UART | `COM4` |
| Serial baud | `115200` |
| HDC UART baud | `921600` |
| Known-good OH6.0 image | `F:\images\PortingTest\6.0\openharmony-spacemit-k1-musepaper2.zip` |
| Preferred OH6.1 Windows staging | `F:\images\PortingTest\6.1\openharmony-spacemit-k1-musepaper2.zip` |

If Linux cannot see the Windows staging directory and `/capabilities` reports
`local_shell=false`, upload the Linux-built zip and flash the artifact id. Do
not claim the image was copied to `F:\images\PortingTest\6.1` unless the
Windows-side copy actually happened.

MusePaper2 can enter flashing mode with:

```bash
python3 tools/oh_autoctl.py shell "reboot fastboot" --wait --connect-channel usb --connect-target 0123456789ABCDEF
python3 tools/oh_autoctl.py serial "reboot fastboot" --wait --port COM4 --baudrate 115200
```

## Boot Escape Policy

Use a stricter policy while the image can panic before HDC:

- `startup.porting.boot_escape.timeout_sec=60`
- `startup.porting.boot_escape.accept_boot_completed=false`
- `startup.porting.boot_escape.ack=false`

This forces a return to fastboot unless command access has been explicitly
acknowledged.

For rc0/test-team builds that already reach boot completed, relax the policy:

- `startup.porting.boot_escape.timeout_sec=120`
- `startup.porting.boot_escape.accept_boot_completed=true`
- `startup.porting.boot_escape.ack=false`

This avoids surprising testers by rebooting a healthy boot-completed system,
while still preserving a recovery escape if boot completed is never reached.
Automation smoke may set `startup.porting.boot_escape.ack=true` after HDC is
verified.

## Runtime Triage

Use this order when the device boots far enough for evidence:

1. HDC/serial connectivity and `reboot fastboot` recovery.
2. `bootevent.*` readiness properties.
3. screenshot or `snapshot_display` proof of UI.
4. service registration through `hidumper -ls` or targeted dumps.
5. functional user-visible checks.
6. log noise correlation.

Promote a log pattern only when it correlates with a failed workflow, crash,
panic, missing device node, or service restart storm.

## HATS Native Smoke Pattern

Build HATS binaries through the HATS wrapper, not ad hoc multi-target
`build.sh` invocations:

```bash
prebuilts/python/linux-x86/current/bin/python3 -B test/xts/hats/build.py \
  suite=/path/to/targets.txt \
  product_name=musepaper2@spacemit \
  target_arch=riscv64 \
  system_size=standard \
  target_subsystem=kernel
```

Run low-risk native binaries with:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_hats_native_runner.py \
  --binary-dir /path/to/out/musepaper2/tests/moduletest/hats/syscalls/fileio \
  --out /path/to/records/iterationNNN/hats_run \
  --iteration-tag iterationNNN \
  --connect-channel usb \
  --connect-target 0123456789ABCDEF \
  HatsOpenatTest HatsRenameatTest
```

Prefer fileio, syscall, HDF read-only, power/input/display smoke subsets early.
Delay tests that change active slot, system time, suspend/lock state, sysctl,
mount namespace, battery/thermal settings, network topology, or USB role until
there is a recovery plan.

## Time-Savings Estimate For Future Similar Ports

If the above lessons are applied from the start and real dependencies are
available:

| Scenario | Expected time | Typical assumptions |
|---|---:|---|
| optimistic | 2.5-3.5 days | same SoC/board family, stable device automation, no new binary gaps |
| normal | 4-6 days | old completed port exists, dependencies present, some OH6.x churn |
| complex | 8-12+ days | new peripheral behavior, missing prebuilts, unstable test rig, heavy upstream churn |

The largest savings come from build-failure taxonomy, strict device automation,
kernel freshness checks, packaged-input audits, and early boot escape. Camera,
Wi-Fi, Bluetooth, Audio, power, and formal XTS/HATS/ACTS still require real
hardware time.
