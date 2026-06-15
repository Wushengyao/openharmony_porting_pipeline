# xDevice Runner

Use `tools/xts_xdevice_runner/` for modular Windows-side xDevice work. The
module keeps the previously validated `tools/oh_xts_xdevice_runner.py` as the
transport backend and adds explicit environment checks, XML parsing, summaries,
flake planning, and baseline comparison.

## Scope

- Supported suites: ACTS, ACTS-Validator, HATS, DCTS, SSTS, or generated suite
  roots with a standard `config/`, `testcases/`, `tools/` layout.
- Device transport: Windows oh-auto service plus HDC.
- First probe style: one harmless module, usually with `--stage-module-only`.
- Formal claim boundary: a small xDevice module pass proves the runner and that
  module. It does not prove full suite certification.

## One-command Probe

```bash
python3 tools/xts_xdevice_runner/run_xdevice_probe.py \
  --suite-dir /path/to/out/musepaper2/suites/hats \
  --suite-name hats \
  --module HatsGetcwdTest \
  --stage-module-only \
  --out-dir /path/to/records/xts_probe \
  --baseline /path/to/acceptance/acceptance_state.yaml
```

The output directory contains:

- `prepare_env.json`
- `runner/xts_xdevice_manifest.json`
- `runner/xdevice_run.json`
- `runner/xdevice_summary.json`
- `reports/collected_reports.json`
- `summary/test_summary.yaml`
- `summary/summary.md`
- optional `regression_matrix.yaml`

`run_xdevice_probe.py` accepts runner arguments after a literal `--`; the
wrapper strips that separator before forwarding arguments to the transport
runner.

When forwarding native xDevice flags that begin with `-`, use the equals form
so the wrapper treats the value as data rather than as its own option. For
OHJSUnit/Hypium cases inside an ACTS HAP, filter through xDevice testargs with
`-ta class:<Class#Case>`:

```bash
python3 tools/xts_xdevice_runner/run_xdevice_probe.py \
  --suite-dir /path/to/out/musepaper2/suites/acts/acts \
  --suite-name acts \
  --module ActsArrayTest \
  --stage-module-only \
  --out-dir /path/to/records/acts_array_4158 \
  -- --extra=-ta --extra='class:ArrayCombinationTest4#ArrayCombinationTest4158'
```

This can still use `--module` and `--stage-module-only` to keep the upload
small. The resulting xDevice command keeps `-l <module>` and passes the class
filter to the OHJSUnit driver, which then runs `aa test ... -s class ...`.

Do not use `-tc <Class#Case>` for OHJSUnit/Hypium HAP-internal case filters.
In this xDevice version `-tc/--testcase` selects a test source or JSON entry,
so `ArrayCombinationTest4#ArrayCombinationTest4158` becomes unavailable instead
of running the case. When `-tc/--testcase` is forwarded for drivers that really
use it, the transport runner omits the module `-l` option because xDevice
treats `-l` and `-tc` as mutually exclusive.

## Step-by-step Commands

Check environment:

```bash
python3 tools/xts_xdevice_runner/prepare_env.py \
  --suite-dir /path/to/suite \
  --out /path/to/out/prepare_env.json
```

Generate or refresh user config:

```bash
python3 tools/xts_xdevice_runner/generate_user_config.py \
  --sn 0123456789ABCDEF \
  --out /path/to/suite/config/user_config.xml
```

Run suite or module:

```bash
python3 tools/xts_xdevice_runner/run_suite.py \
  --suite-dir /path/to/suite \
  --suite-name acts \
  --module ActsStartupSysDeviceInfoTest \
  --stage-module-only \
  --out /path/to/out/runner
```

For drivers that prompt on stdin, pass one line per prompt:

```bash
python3 tools/xts_xdevice_runner/run_suite.py \
  --suite-dir /path/to/suite \
  --suite-name acts-validator \
  --module validator \
  --stdin-line Y \
  --out /path/to/out/runner
```

This only removes the non-interactive EOF failure. A module still needs real
case XML or xDevice pass/fail counts before it can be considered passed.

Collect/index reports:

```bash
python3 tools/xts_xdevice_runner/collect_reports.py \
  --runner-dir /path/to/out/runner \
  --out-dir /path/to/out/reports \
  --pull-text-from-runner
```

When `--pull-text-from-runner` is set, the collector reads the Windows
`report_file_list.json` produced by the transport runner and pulls small text
artifacts back through oh-auto admin shell. This covers XML, HTML, INI, log,
TXT, and RECORD files. Small `.gz` log artifacts are pulled as bytes through
PowerShell `ReadAllBytes` plus base64 so compressed hilog is preserved. Other
binary or oversized artifacts stay indexed by path only.

Parse local XML reports when they are available:

```bash
python3 tools/xts_xdevice_runner/parse_xml.py \
  --report-root /path/to/reports \
  --out /path/to/out/parsed_xml.json
```

Summarize:

```bash
python3 tools/xts_xdevice_runner/summarize.py \
  --runner-dir /path/to/out/runner \
  --parsed-xml /path/to/out/parsed_xml.json \
  --out-dir /path/to/out/summary
```

Compare with baseline:

```bash
python3 tools/xts_xdevice_runner/compare_baseline.py \
  --current /path/to/out/summary/test_summary.yaml \
  --baseline /path/to/acceptance/acceptance_state.yaml \
  --out /path/to/out/regression_matrix.yaml
```

Create rerun plan:

```bash
python3 tools/xts_xdevice_runner/flaky_detector.py \
  --input run1/parsed_xml.json \
  --input run2/parsed_xml.json \
  --out rerun_plan.yaml
```

## Tool Package Handling

The Windows transport runner uninstalls stale `xdevice*` packages, pins
`setuptools<81`, and normalizes xDevice tarball names before pip install. Some
source-built suites contain both underscore and hyphen spellings of the same
package, such as `xdevice_devicetest` and `xdevice-devicetest`; installing both
causes pip `ResolutionImpossible`, so only one normalized package is selected.

XML parsing treats `status=skip/skipped`, `status=ignored`, and unavailable
cases as non-failures before looking at `result=false`; xDevice can emit
`status="skip" result="false"` for intentional gtest skips. It also treats
`status=disable/disabled`, `status=blocked`, XML `disabled` counters, or
messages containing `mark blocked` as blocked. This matches reports that mark
downstream cases blocked after the first real failure. For runnable cases,
`result=true/false` is authoritative for case pass/fail. The parser does not
promote `status=run` to pass, deduplicates cases that appear in both
`summary_report.xml` and per-module XML, and keeps the failure list limited to
real `failed`, `error`, or `timeout` cases.

For long-running CppTest probes, pass `--native-test-timeout-ms <ms>` after the
`run_xdevice_probe.py -- ...` separator. The runner patches only the staged
module `Test.json`, records the patch in `module_staging_manifest.json`, and
does not modify the OpenHarmony source tree.

## Current MusePaper2 Evidence Boundary

MusePaper2 OH6.1 has proven xDevice transport and selected modules:

- HATS `HatsGetcwdTest`: 1/1 passed.
- HATS syscall expansion through xDevice: `HatsClockGetresTest`,
  `HatsNanoSleepTest`, `HatsChdirTest`, `HatsDupTest`, `HatsDup3Test`,
  `HatsEventfd2Test`, `HatsEpollCreateTest`, and `HatsFaccessatTest` passed in
  iteration342.
- HATS syscall/FS/FD expansion through xDevice continued in iteration343:
  `HatsFchmodTest`, `HatsFtruncateTest`, `HatsGetcwdTest`,
  `HatsGetdents64Test`, `HatsLseekTest`, `HatsPipe2Test`, `HatsReadvTest`,
  `HatsWritevTest`, `HatsFcntlTest`, `HatsFdatasyncTest`, `HatsFsyncTest`,
  `HatsFstatfsTest`, `HatsFlockTest`, `HatsLinkatTest`, `HatsMkdiratTest`,
  and `HatsReadlinkatTest` passed.
- HATS syscall/FS/process expansion continued in iteration344:
  `HatsPread64Test`, `HatsPwrite64Test`, `HatsPselectTest`, `HatsPpollTest`,
  `HatsRenameatTest`, `HatsSymlinkatTest`, `HatsUnlinkatTest`,
  `HatsPreadvTest`, `HatsPwritevTest`, `HatsCapGetTest`,
  `HatsClockNanoSleepTest`, `HatsCopyFileRangeTest`, `HatsEpollCtlTest`,
  `HatsEpollPwaitTest`, `HatsFchmodatTest`, `HatsGetrlimitTest`,
  `HatsGetrusageTest`, `HatsSysinfoTest`, and `HatsTimesTest` passed with
  60/60 cases through Windows-side xDevice.
- HATS xDevice expansion continued in iteration346. Memory/scheduler/file
  syscall modules plus Light/Vibrator/Sensor/Input HDF modules passed in
  batches 7-11: 28 additional modules, 454/454 cases. The HATS xDevice coverage
  stood at 88/99 modules and 15574 passed cases after that iteration. Remaining
  modules were concentrated in DMA/Display/USB/Startup partition slot, Audio
  HDF, and Power/Battery/Thermal.
- HATS Audio HDF expansion continued in iteration347. The nine remaining Audio
  HDF modules gained xDevice pass evidence: 861 total cases, 860 passed, one
  intentional ignored/skipped case, zero failed. Manager, ManagerAdditional,
  and EffectAdditional passed as plain xDevice modules. Adapter, Render, and
  Capture direct-HDI modules require stopping `audio_server`, restarting
  `audio_host`, running the module, then restoring `audio_server`.
  `HatsHdfAudioIdlCaptureAdditionalTest` additionally needs staged
  `native-test-timeout=600000`; the default 120000 ms causes
  `ShellCommandUnresponsiveException` and downstream blocked cases.
- HATS remaining-module expansion continued in iteration348. Ten non-Audio
  modules passed through formal xDevice: DMA buffer, Display buffer UT, USB auto
  function, Power, Battery, and Thermal groups. Best result: 232 total cases,
  230 passed, 2 ignored/skipped, zero failed. Do not run
  `HatsStartupPartitionSlotTest` unattended: it mutates active and unbootable
  boot slot state, and requires a proven physical recovery backend or dedicated
  fixture before full-module execution.
- ACTS `ActsStartupSysDeviceInfoTest`: 85/85 passed.
- ACTS `ActsHilogNdkTest`: 64/64 passed after the RISC-V native assistant HAP
  and SDK libc++ ABI fixes. The rerun also pulled back XML/HTML/log evidence
  from the Windows xDevice report directory.
- ACTS pure JS expansion through xDevice: `ActsPromiseTest`, `ActsDataViewTest`,
  and `ActsBaseSpecTest` passed in iteration342. `ActsArrayTest` is a stable
  partial full-module failure at `ArrayCombinationTest4158` with downstream
  blocked cases, but iteration349 narrowed it using `-ta class:` filters:
  `ArrayCombinationTest4158` alone passes, `4154-4158`/`4155-4158`/`4156-4158`
  /`4157-4158` pass, while `4153-4158` and `4148-4158` fail at `4158`.
  Iteration350 confirmed that `4153,4158`, several 3-5 case subsets, and all
  tested five-case subsets pass, but the complete `4153-4158` six-case window
  fails again at `4158`. Treat it as a higher-order
  sequence/state/resource interaction across `ArrayCombinationTest4Js153-158`
  before changing product runtime code or weakening the test.
- ACTS pure JS/AppInstallKit-only expansion continued in iteration343:
  `ActsDateTest`, `ActsRegExpTest`, `ActsSymbol1Test`, `ActsSymbol2Test`,
  `ActsMapTest`, and `ActsProxyTest` passed. Do not rely on module names alone:
  inspect each `testcases/<module>.json` before running; for example,
  `ActsJsonJSApiTest` is JS-related but includes `ShellKit` power-mode commands
  and was intentionally deferred from the low-risk batch.
- ACTS `ActsObjectTest` is a real partial xDevice result, not a transport
  failure. Iteration344 reported one failed case at `Object1Test036`, but
  iteration345 reruns drifted to later cases after earlier cases passed, which
  points to test process, runner early-end, or flaky execution before treating
  the source assertion as a fixed Ark/ETS builtins failure. Keep it open until
  rerun evidence stabilizes or a runner/app-side cause is isolated.
- ACTS-Validator: dispatch reached xDevice, but generated validator resources
  were incomplete. A later probe showed `queryStandard` can be supplied by full
  suite staging and `--stdin-line Y` can remove the prompt EOF, but the module
  still reports `unavailable` with zero tests when the validator app does not
  generate `Test.xml`.
- DCTS: module executed on one device, but meaningful pass/fail likely requires
  distributed or dual-device topology.
- SSTS: OHYaraTest executed, but the sample was blocked by security patch label
  policy.

Keep these as engineering evidence. Do not promote them to full formal suite
acceptance without complete reports and matching official resource/version
requirements.
