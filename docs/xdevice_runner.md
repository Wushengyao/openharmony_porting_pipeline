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

Collect/index reports:

```bash
python3 tools/xts_xdevice_runner/collect_reports.py \
  --runner-dir /path/to/out/runner \
  --out-dir /path/to/out/reports
```

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

## Current MusePaper2 Evidence Boundary

MusePaper2 OH6.1 has proven xDevice transport and selected modules:

- HATS `HatsGetcwdTest`: 1/1 passed.
- ACTS `ActsStartupSysDeviceInfoTest`: 85/85 passed.
- ACTS-Validator: dispatch reached xDevice, but generated validator resources
  were incomplete.
- DCTS: module executed on one device, but meaningful pass/fail likely requires
  distributed or dual-device topology.
- SSTS: OHYaraTest executed, but the sample was blocked by security patch label
  policy.

Keep these as engineering evidence. Do not promote them to full formal suite
acceptance without complete reports and matching official resource/version
requirements.
