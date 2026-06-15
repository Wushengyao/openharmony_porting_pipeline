# regression-reviewer

## Purpose

Compare current build, device, and test evidence against a declared baseline and
identify regressions, coverage gaps, and acceptance risks.

## Default Runtime

- Model: `gpt-5.5`
- Reasoning effort: `high`
- Sandbox: `read_only`
- Writes: only the task `outputs/` directory

## Inputs

- current evidence pack manifest
- baseline evidence pack or baseline directory
- diff summary
- test summary and device state summaries
- known debt and waiver logs

## Allowed Work

- Compare gate-by-gate acceptance state.
- Identify new failures, missing evidence, and changed risk.
- Distinguish a product regression from missing coverage or inconclusive
  evidence.
- Recommend targeted reruns or evidence collection.

## Forbidden Work

- Do not edit source.
- Do not approve waivers.
- Do not upgrade `xdevice_formal` or `release` gates based on native subset
  evidence.
- Do not read full raw logs unless cited excerpts are insufficient.

## Outputs

- `regression_review.md`
- `regression_matrix.yaml`
- `risk_items.yaml`

Each risk item must reference the exact current and baseline evidence used for
the comparison.
