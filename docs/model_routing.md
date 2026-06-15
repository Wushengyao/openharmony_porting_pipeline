# Model Routing

`policies/model_routing.yaml` is the machine-readable source of truth. This
document explains the intent.

## Main Agent

Use the strongest available reasoning model for:

- decomposition of an ambiguous porting goal
- high-risk operation decisions
- patch merge decisions
- regression and release-gate judgment
- final RC or release wording

## Read-Heavy Subagents

Use a smaller fast model when the task is bounded and evidence is already
prepared:

- `repo-surveyor`
- `build-log-triager`
- `xts-hats-runner` summary mode
- `reporter` draft mode
- `device-automation-steward` summary mode

Upgrade when evidence is conflicting, the same failure repeats, or the finding
touches boot, HDF, init, permissions, firmware, binary assets, or release gates.

## High-Judgment Roles

Use the strongest model for:

- `regression-reviewer`
- `patch-planner`
- `patch-writer`
- `runtime-hdf-reviewer`
- `binary-asset-auditor`
- `version-lane-maintainer`
- `skill-maintainer`

These roles can affect source edits, risk classification, or future reusable
rules, so low-cost routing is usually false economy.

## Budget Discipline

Do not spend model context on full raw logs by default. First run:

- `tools/evidence_pack_builder.py`
- `tools/log_slice.py`
- test-report parsers or xDevice runners
- risk scanners

The main Agent should request raw excerpts only when evidence references are
ambiguous or a high-risk decision needs exact text.
