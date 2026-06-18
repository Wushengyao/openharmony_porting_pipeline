# OpenHarmony Formal XTS And xDevice Workflow

Use this reference when a porting task moves from native smoke tests into
formal XTS/xDevice execution, when official XTS resources must be fetched, or
when a Windows workbench is the only host that can see the target through HDC.

## Official Inputs

- Treat `https://www.openharmony.cn/systematic?tab=xts` as the user-facing
  entry. The SPA loads the machine-readable document from
  `https://compatibility.openharmony.cn/certificate/external/document/xts`.
- Also fetch the compatibility guide from
  `https://compatibility.openharmony.cn/certificate/external/document/guid`
  when documenting the full certification flow.
- Persist the raw JSON and a Markdown extraction in the iteration record before
  downloading suites or resources. The page can change independently of the
  source tree.

## Version, Architecture, And Resource Rules

- Match image version, suite version, resource package, and system type. Do not
  use an older official suite or resource as formal evidence for a newer target
  release unless the official page explicitly says it is shared.
- Preserve the original failing suite as immutable evidence. For fix closure,
  rerun the same downloaded archive or generated suite root, testcase binaries,
  JSON/moduleInfo files, resource package, xDevice tool bundle, module list,
  and case-count surface that produced the baseline failure whenever those
  artifacts are runnable on the target.
- Do not modify testcase artifacts to make a result pass. This includes editing
  testcase binaries, JSON/moduleInfo, expected values, resource files, disabled
  markers, test lists, filters, or runner staging copies. Changes to transport
  configuration such as target SN, report path, and user config are allowed only
  when they do not change selected tests or expected results.
- If the original suite cannot run because no matching architecture, system
  type, resource, or toolchain exists, record that as official-resource or
  tooling debt. A same-release source-built suite may support engineering
  validation, but it must not be reported as the original suite passing.
- If a source-built or otherwise regenerated suite changes testcase counts,
  module membership, tool bundles, or expected behavior, compare it with the
  original baseline and state the difference explicitly before claiming any
  closure.
- Official standard-system executable suites may be published only for a common
  architecture such as arm32. For RISC-V64, arm64, x86, small-system, or
  otherwise missing targets, build the suites from the matching OpenHarmony
  release source instead of running the wrong prebuilt.
- If the target release is not listed on the official XTS download page, record
  the gap and use same-release source-built suites for engineering validation.
  Do not silently mix the newest listed resource set into the target release.
- Download resource packages only when the official page has an exact matching
  release and system type. Place them under `<suite>/resource` or pass
  `-respath <resource-dir>`.
- Some signed OBS URLs are signed for GET; `curl -I` can fail with
  `SignatureDoesNotMatch`. Use the official page/API as the source of truth and
  prefer an actual controlled download when the version match is valid.

## Suite Build And Layout

- For a standard-system product, the formal suite set is normally ACTS,
  ACTS-Validator, HATS, DCTS, and SSTS. DCTS may need a distributed test box or
  two-device network setup.
- Build target-architecture suites from the target workspace, for example:

```bash
cd test/xts/hats
./build.sh product_name=<product> system_size=standard
```

- On hosts where `/usr/bin/python3` is older than Python 3.10, run XTS build
  wrappers with the OpenHarmony prebuilt Python first in `PATH`; the OH6.1 XTS
  CI helpers use syntax such as `str | None`:

```bash
PATH="$PWD/prebuilts/python/linux-x86/3.11.4/bin:$PATH" \
  ./test/xts/acts/build.sh product_name=<product> system_size=standard \
  target_arch=riscv64 xts_suitetype=bin,hap_dynamic
```

DCTS uses the same prebuilt-Python rule. Put Python 3.11 in `PATH` before
invoking `test/xts/dcts/build.sh`; otherwise the wrapper can start under host
Python 3.8 and fail before it updates `PATH` internally:

```bash
PATH="$PWD/prebuilts/python/linux-x86/3.11.4/bin:$PATH" \
  ./test/xts/dcts/build.sh product_name=<product> system_size=standard \
  target_arch=riscv64 xts_suitetype=bin,hap_dynamic
```

- For OH6.1 RISC-V ACTS, if GN fails at
  `test/xts/acts/commonlibrary/toolchain/BUILD.gn` with `rebase_path("")`,
  compare the already-ported OH6.0 RISC-V tree. The expected fix is to add a
  `target_cpu == "riscv64"` branch to `tar_dllib`, mirroring arm64/x86_64 and
  generating `libc-test-lib.tar`; do not drop the commonlibrary/toolchain ACTS
  coverage.
- If Ninja then reports a missing SDK library under
  `prebuilts/ohos-sdk/linux/<api>/native/sysroot/usr/lib//`, inspect
  `build/ohos_var.gni`. OH6.1 original may lack the RISC-V branch for
  `target_platform_triple`; add `target_platform_triple =
  "riscv64-linux-ohos"` for `target_cpu == "riscv64"` so ACTS NDK tests use the
  existing architecture-specific SDK libraries instead of flattening them into
  `usr/lib`.
- If a source-built ACTS HAP lacks `libs/riscv64`, first add `riscv64` to the
  HAP `abiFilters`, then make the SDK/Hvigor chain accept and link
  `riscv64-linux-ohos`. The minimum shape observed on one OH6.1 RISC-V port
  included
  Hvigor ABI enum/schema entries, a CMake toolchain branch, RISC-V musl sysroot
  startup files and headers, compiler-rt crt/builtins, `libunwind.a`, and NDK
  libc++ libraries.
- Treat `build-profile.json5` ABI changes as weakly tracked by the XTS GN/Ninja
  app graph. If the XTS wrapper re-signs stale unsigned HAPs without re-running
  Hvigor `compile_app.py`, clean the affected module `*/build` outputs and both
  the module and companion LibTest obj/stamp/unsigned-list outputs before
  rebuilding through `test/xts/acts/build.sh`. If only the module target is
  cleaned, LibTest signing can fail because its unsigned list points at deleted
  or stale HAP/HSP files.
- If the cleaned Hvigor RISC-V HAP build then fails with
  `libunwind.a(libunwind.cpp.o): unable to find library from dependent library
  specifier: dl`, inspect the SDK sysroot before changing test code. In one
  OH6.1 RISC-V port, `libunwind.a` carried `.deplibs = dl` while
  `prebuilts/ohos-sdk/linux/<api>/native/sysroot/usr/lib/riscv64-linux-ohos/`
  had `libm.a` but lacked `libdl.a` and `libpthread.a`. Copying the same-release
  musl empty archives from
  `out/<product>/obj/third_party/musl/usr/lib/riscv64-linux-ohos/` into the SDK
  sysroot let the required `build.sh` HAP target complete and converted
  `ActsPreferencesNdkTest` from 0/67 to 67/67 through xDevice. Record this as an
  SDK/sysroot completeness fix, not a product feature reduction.
  The skill helper can perform this reproducibly:
  `python3 tools/sync_riscv_sdk_sysroot_libs.py --workspace /path/to/ohos --product <product> --api <api> --apply`.
- For RISC-V libc++, verify the ABI namespace with `llvm-nm -C`. If one libc++
  exports a different namespace than the HAP object and device
  `libc++_shared.so`, use the same NDK libc++ family for the SDK RISC-V libs.
  This has resolved
  `std::__n1::basic_string` link failures.
- If `third_party/vk-gl-cts` fails for RISC-V with missing or wrong dEQP target
  defines, add the riscv64 target branch in `vk_gl_cts.gni`: `DE_PTR_SIZE=8`
  and `DE_CPU=DE_CPU_RISCV_64`. Keep the Vulkan/GLES test coverage; do not
  remove the ACTS graphics modules just to pass the build.
- If `ActsDemuxerTest` reports `AV_CODEC_PATH` macro redefinition between
  `/system/lib` and `/system/lib64`, treat riscv64 as a 64-bit platform in
  `test/xts/acts/multimedia/av_codec/demuxer/BUILD.gn` and route it to
  `/system/lib64`.
- Generated suite roots are typically under `out/<product>/suites/<suite>` and
  contain `run.bat`, `run.sh`, `config/user_config.xml`, `testcases/`, and
  `tools/xdevice*.tar.gz`.
- Some XTS build wrappers create a nested suite layout. For ACTS, the outer
  directory may be `out/<product>/suites/acts`, while the actual xDevice roots
  are `out/<product>/suites/acts/acts` and
  `out/<product>/suites/acts/acts-validator`.
- DCTS may generate a direct xDevice root at `out/<product>/suites/dcts` with
  the standard
  `run.bat/run.sh/config/testcases/tools` layout.
- Full ACTS can be large; avoid whole-suite upload for first probes unless the
  device and Windows workbench storage path have been preflighted.

## Closed-Loop Acceptance Boundary

For a newly stabilized port, distinguish three evidence levels:

- Tooling/transport closure: xDevice can install, run, collect, parse, and
  summarize at least one low-risk module from each applicable suite root.
- Engineering closure: failed modules are driven through
  report -> failure packet -> source/tool/topology classification -> fix ->
  build/package/flash/smoke -> non-filtered full-module rerun using the
  original failing suite artifacts when runnable.
- Acceptance closure: every applicable suite has a full-suite or reviewed
  quasi-full report, with pass evidence or explicit exception records for
  unavailable official resources, manual ACTS-Validator steps, DCTS topology,
  SSTS security-patch policy, and safety-gated destructive tests.

Once the target image is bootable, command-accessible, and recoverable without
manual reset, prefer long-running module queues over only ad hoc probes. Use
filtered class/case/window probes to minimize failures, but never promote them
to suite pass evidence. A pass from a rebuilt, filtered, timeout-patched, or
otherwise changed suite is diagnostic or engineering evidence only unless the
same original-suite module also passes. After every XTS-related iteration,
refresh the global suite progress snapshot and report deltas in module
coverage, passed modules, and known report-derived testcase counts.

## Windows Workbench Execution

- The official workflow assumes a Windows workbench connected to the standard
  system device by USB. For remote build servers, the target may be visible only
  through Windows oh-auto; Linux-local `hdc` may not see it.
- Keep one xDevice tool bundle active per run. Different suites may ship
  different `xdevice-0.0.0` contents under the same package name, so stale
  installs can mix a new plugin with an old base package.
- Query oh-auto before a formal run:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py status
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py admin-status
```

- If oh-auto has admin support, stage the suite zip to a Windows allowed root
  from the active profile or `/capabilities`, expand it, and run xDevice from
  the Windows side. Prefer `tools/oh_xts_xdevice_runner.py` for repeatable
  staging, xDevice install, execution, report listing, and summary parsing; use
  raw `admin-shell` only for trusted lab maintenance.
- For closed-loop evidence, prefer the modular
  `tools/xts_xdevice_runner/run_xdevice_probe.py` wrapper. It stages/runs the
  suite through the transport runner, parses the runner summary, pulls small
  XML/HTML/INI/log text reports from the Windows report directory, parses local
  XML, and emits `summary/test_summary.yaml`.
- For ACTS OHJSUnit/Hypium HAP-internal class/case triage, prefer the semantic
  wrapper options `--ohjsunit-class <ClassName>` and
  `--ohjsunit-case <ClassName#CaseName>`. They emit the validated xDevice
  testargs form `-ta class:<...>` and avoid repeated hand-written CLI mistakes.
  The raw fallback is `-- --extra=-ta --extra='class:<Class#Case>'`.
  Do not use `--extra=-tc --extra='<Class#Case>'` for this purpose; in xDevice
  5.0.6.100 `-tc/--testcase` selects a test source or JSON entry, so
  HAP-internal cases become `unavailable` instead of running. If a driver
  genuinely needs `-tc/--testcase`, remember xDevice treats it as mutually
  exclusive with `-l/--testlist`.
- For large OHJSUnit modules, use
  `tools/xts_xdevice_runner/run_ohjsunit_class_batches.py` as a triage tool.
  Class or exact-case pass evidence proves only that filtered scope. Do not
  mark the whole module closed until a full-module run passes, or until every
  residual failure is explicitly classified as a runner/framework limitation
  with rerun evidence.
- Use the Python interpreter reported by oh-auto capabilities/admin status, not
  the Windows Store `python` shim. Confirm `hdc` resolves to the workbench HDC:

```powershell
Get-Command hdc
& '<hdc.exe>' list targets
```

## Minimal Formal Probe

Start with one harmless module before a broad suite:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_xts_xdevice_runner.py \
  --suite-dir /path/to/ohos/out/<product>/suites/hats \
  --out /path/to/work/records/iterationNNN/runner_hats_getcwd \
  --run-id iterationNNN_hats_getcwd \
  --module HatsGetcwdTest \
  --command-timeout-sec 600 \
  --upload-timeout-sec 1200
```

The runner writes `xts_xdevice_manifest.json`, staged zip upload/promote
evidence, `xdevice_run.json`, `xdevice_summary.json`, and
`report_file_list.json`. Its default report path includes `run_id` so repeated
probes do not reuse a non-empty xDevice report directory.
If the run was launched through `tools/xts_xdevice_runner/run_xdevice_probe.py`,
also preserve `reports/collected_reports.json`,
`reports/pulled_reports.json`, local `reports/reports/**` files,
`parsed_xml.json`, and `summary/test_summary.yaml`.

For large suites such as ACTS, run a module-only staging probe first. The runner
copies `config/`, `tools/`, optional `run.bat/run.sh`, and testcase files
referenced by the selected module JSON:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_xts_xdevice_runner.py \
  --suite-dir /path/to/ohos/out/<product>/suites/acts/acts \
  --out /path/to/work/records/iterationNNN/runner_acts_deviceinfo \
  --run-id iterationNNN_acts_deviceinfo \
  --module ActsStartupSysDeviceInfoTest \
  --stage-module-only \
  --command-timeout-sec 600 \
  --upload-timeout-sec 600
```

Module-only staging keeps the Windows transfer small while still exercising the
official xDevice driver/config/testcase path. Keep the manifest's
`staged_testcases` list with the run evidence.

For external resource suites such as SSTS, the downloaded suite may include an
older xDevice bundle than the one generated from the target source tree. If
`python -m xdevice` fails with `pkg_resources` or `cannot import name
'CaseEnd'`, run the same suite content with a known-good same-release tool
bundle by overriding `tools/`:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_xts_xdevice_runner.py \
  --suite-dir /path/to/unpacked/ssts \
  --tools-dir /path/to/ohos/out/<product>/suites/acts/acts/tools \
  --out /path/to/work/records/iterationNNN/runner_ssts_probe \
  --run-id iterationNNN_ssts_probe \
  --module OpenHarmony-SA-2025-11 \
  --resource-dir '<windows-xts-run-root>\iterationNNN_ssts_probe\ssts\resource'
```

The runner uninstalls stale `xdevice*` packages before each install, pins
`setuptools<81` for legacy `pkg_resources` imports under Windows Python 3.12,
normalizes underscore and hyphen package spellings, and installs only one
tarball per normalized xDevice package name. This avoids pip conflicts when a
suite ships both `xdevice_devicetest` and `xdevice-devicetest`.

Manual equivalent:

```powershell
Set-Location '<windows-suite-root>'
& '<python.exe>' `
  -m pip uninstall -y xdevice xdevice-extension xdevice-ohos xdevice-devicetest
& '<python.exe>' `
  -m pip install --user --force-reinstall 'setuptools<81'
& '<python.exe>' `
  -m pip install --user .\tools\xdevice-0.0.0.tar.gz `
  .\tools\xdevice_devicetest-0.0.0.tar.gz `
  .\tools\xdevice_ohos-0.0.0.tar.gz
& '<python.exe>' `
  -m xdevice run -l HatsGetcwdTest -sn <target-sn> `
  -c .\config\user_config.xml -tcpath .\testcases -rp .\reports_probe_getcwd
```

Important details:

- `-c` must point to `config/user_config.xml`, not the `config` directory.
- `-rp .\name` is placed under the suite `reports` directory; for the example
  above the effective path is `hats\reports\reports_probe_getcwd`.
- xDevice can run `remount`, start hilog capture, push tests into
  `/data/local/tmp`, and leave XML outputs on device. Record or clean leftovers
  deliberately.
- Do not start with broad audio, suspend, USB-role, network-topology, active
  slot, or distributed suites. Use clean boots and per-module reboot isolation
  for stateful modules.
- A single low-risk DCTS module can be used to prove that xDevice can stage and
  launch DCTS. Do not treat DCTS failures as product regressions until a
  two-device or lab-distributed topology is prepared; DCTS modules cover
  distributed scheduling, SoftBus, distributed data, distributed hardware, and
  paired client/server apps.

## Evidence To Preserve

For each formal XTS/xDevice run, keep:

- official XTS and guide JSON/Markdown snapshots;
- exact suite source workspace, product name, build command, suite root, and
  suite zip hash;
- official resource manifest and downloaded resource hashes, or a recorded
  reason that no matching resource exists;
- oh-auto capabilities/status/profile before and after the run;
- xDevice install/help output when bootstrapping a workbench;
- xDevice command line, stdout/stderr, report directory, `summary.ini`,
  `summary_report.xml`, module result XMLs, module/task logs, and report zip
  hash;
- device version and architecture evidence such as `uname -m` and
  `param get const.product.software.version`.

When parsing xDevice XML, classify disabled and blocked cases before looking at
`result=false`. ACTS reports can emit `status="disable" result="false"` with a
`mark blocked` message for cases that were skipped after the first real
failure. These cases are blocked debt, not individual testcase failures. Also
classify `status="skip"` or `status="ignored"` before `result=false`; HATS can
emit `status="skip" result="false"` for an intentional gtest skip.

When narrowing ACTS OHJSUnit/Hypium failures, do not stop after a single-case
probe. Record both passing subsets and failing windows before classifying an
Ark/ETS builtin assertion as a product-runtime defect. A case that passes alone
but fails in a sequence may indicate AppFreeze, foreground state, lifecycle
cleanup, resource pressure, or runner behavior rather than pure language
semantics.

Treat ACTS OHJSUnit/Hypium foreground tests as focus/lifecycle sensitive.
During a formal or evidence-producing xDevice run, do not issue sidecar HDC,
shell, hilog, screenshot, or manual UI operations unless the run is explicitly
diagnostic and marked contaminated. System dialogs, including power popups, can
steal focus or alter the test ability lifecycle; discard overlapping results
and rerun after clearing the UI.

Do not blindly batch tests that mutate boot metadata, suspend state, USB role,
network topology, filesystem mounts, or distributed topology. Treat such
modules as safety-gated until automatic recovery, a dedicated fixture, or a
clearly labeled read-only/filter probe is available.

For CppTest modules whose generated `Test.json` timeout is too short, use the
runner's staged-only timeout patch instead of editing OpenHarmony source:

```bash
python3 tools/xts_xdevice_runner/run_xdevice_probe.py \
  --suite-dir out/<product>/suites/hats \
  --suite-name hats \
  --module <module> \
  --stage-module-only \
  --out-dir /path/to/out \
  -- --native-test-timeout-ms 600000
```

Treat any staged timeout patch as diagnostic unless the unmodified original
suite artifacts also pass under the required formal timeout policy.

Record DCTS launch evidence separately from DCTS pass/fail until a required
distributed or multi-device topology is prepared. Record ACTS-Validator
interactive prompts, generated-resource gaps, and manual steps separately from
product regressions. For SSTS, record package version, resource hashes, tool
bundle version, security patch label, and policy blocks separately from runner
failures.

Keep device-specific evidence boundaries, pass lists, image paths, target ids,
and historical module outcomes in a device reference, not in this common formal
workflow. For MusePaper2 OH6.1, use `references/musepaper2_oh61_lessons.md`.
