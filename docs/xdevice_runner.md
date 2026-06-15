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
TXT, and RECORD files; binary or oversized artifacts stay indexed by path only.

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

XML parsing treats `status=disable/disabled`, `status=blocked`, or messages
containing `mark blocked` as blocked before looking at `result=false`. This
matches xDevice reports that mark downstream cases blocked after the first real
failure. For runnable cases, `result=true/false` is authoritative for case
pass/fail. The parser does not promote `status=run` to pass, deduplicates cases
that appear in both `summary_report.xml` and per-module XML, and keeps the
failure list limited to real `failed`, `error`, or `timeout` cases.

## Current MusePaper2 Evidence Boundary

MusePaper2 OH6.1 has proven xDevice transport and selected modules:

- HATS `HatsGetcwdTest`: 1/1 passed.
- HATS syscall expansion through xDevice: `HatsClockGetresTest`,
  `HatsNanoSleepTest`, `HatsChdirTest`, `HatsDupTest`, `HatsDup3Test`,
  `HatsEventfd2Test`, `HatsEpollCreateTest`, and `HatsFaccessatTest` passed in
  iteration342.
- ACTS `ActsStartupSysDeviceInfoTest`: 85/85 passed.
- ACTS `ActsHilogNdkTest`: 64/64 passed after the RISC-V native assistant HAP
  and SDK libc++ ABI fixes. The rerun also pulled back XML/HTML/log evidence
  from the Windows xDevice report directory.
- ACTS pure JS expansion through xDevice: `ActsPromiseTest`, `ActsDataViewTest`,
  and `ActsBaseSpecTest` passed in iteration342. `ActsArrayTest` is a stable
  partial failure: 489 passed, one real failed case
  `ArrayCombinationTest4158`, and 3357 blocked cases after rerun.
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
