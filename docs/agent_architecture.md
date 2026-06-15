# Codex Subagent Architecture

This document defines the v0.2 operating model for evolving the OpenHarmony
porting pipeline from a single long-running Agent loop into a main-Agent plus
bounded subagent workflow. It is a contract layer: it can be used with Codex
native subagents, the Codex SDK, or a manual dispatcher as long as the task and
evidence schemas are preserved.

## Goals

- Keep the existing build, package, flash, reconnect, log capture, screenshot,
  HATS, xDevice, and fix loop intact.
- Move noisy read-heavy work out of the main Agent context.
- Require every conclusion to cite evidence paths, commands, log offsets,
  report files, image hashes, screenshots, or source revisions.
- Keep the main Agent responsible for planning, risk decisions, patch merge, and
  final acceptance.
- Allow only one writer for an OpenHarmony workspace at a time.

## Layer Model

L0 deterministic tools execute repeatable actions:

- build and package runners
- flash and reconnect runners
- HDC, serial, screenshot, and bugreport collectors
- HATS native and xDevice runners
- `tools/evidence_pack_builder.py`, `tools/log_slice.py`,
  `tools/panic_classifier.py`, XML parsers, baseline comparators, and risk
  scanners
- oh-auto and future rig-controller clients

L1 subagents perform bounded tasks:

- `repo-surveyor` locates relevant files and module boundaries.
- `build-log-triager` slices logs, matches known signatures, and ranks root
  cause candidates.
- `xts-hats-runner` executes or summarizes test runs and emits structured
  results.
- `regression-reviewer` compares current evidence against a baseline.
- `reporter` drafts status, RC, and handoff reports from structured inputs.
- `skill-maintainer` updates this skill repository after an iteration.
- `patch-planner` prepares risk-scoped patch plans.
- `patch-writer` applies approved edits while holding the writer lock.
- `runtime-hdf-reviewer` reviews boot/init/HDF/runtime evidence.
- `device-automation-steward` operates approved device automation.
- `binary-asset-auditor` inventories prebuilts, firmware, and closed assets.
- `version-lane-maintainer` maintains reusable upgrade lanes.

L2 main Agent owns judgment:

- decomposes the user request into task specs
- dispatches read-only subagents and deterministic tools
- consumes evidence packs and structured summaries instead of full logs
- approves or rejects patch plans and high-risk operations
- owns final RC, release, and handoff claims

L3 supervision and evaluation:

- historical replay evals
- token, time, build, flash, and test cost accounting
- failure-taxonomy coverage tracking
- RC acceptance and high-risk operation audits
- skill evolution review

## Task Contract

Every subagent task must live under a task directory:

```text
agent_tasks/<task_id>/
  task.yaml
  inputs/
  outputs/
  logs/
  evidence/
```

`task.yaml` must validate against `schemas/agent_task.schema.json`. The task
must name the role, model label, workspace, sandbox, allowed tools, forbidden
actions, inputs, outputs, budget, stop conditions, and risk-escalation rules.

Subagents must return machine-readable outputs first. Markdown summaries are
allowed, but they are secondary and must not be the only result.

## Evidence Pack Contract

The main Agent should read a compact evidence pack for each iteration or job:

```text
evidence_packs/<iteration_or_job_id>/
  manifest.yaml
  build_summary.yaml
  test_summary.yaml
  device_state.yaml
  diff_summary.md
  top_errors.md
  screenshots/
  serial_excerpt.log
  hdc_excerpt.log
  links_to_raw_artifacts.md
```

`manifest.yaml` must validate against `schemas/evidence_pack.schema.json`.
Large raw logs, full XML reports, and full serial captures stay in the raw
artifact root and are referenced by path plus offset or range.

## Acceptance State

Do not collapse adjacent gates. The acceptance state must record each gate
independently:

```text
build_passed != package_passed
package_passed != flash_passed
flash_passed != boot_passed
boot_passed != hdc_connected
hdc_connected != ui_passed
ui_passed != subsystem_smoke_passed
subsystem_smoke_passed != hats_native_subset_passed
hats_native_subset_passed != xdevice_formal_passed
xdevice_formal_passed != release_accepted
```

Use `schemas/acceptance_state.schema.json` for the state file. Each gate needs
a status, evidence references, timestamp when available, and debt or waiver
links when the result is partial or accepted with known risk.

## Writer Policy

Default subagent sandbox is read-only.

Only a `patch-writer` or `skill-maintainer` task may write, and only inside its
declared write roots. An OpenHarmony source workspace may have only one writer
Agent at a time. The main Agent owns the writer lock and must record:

- task id
- allowed paths
- start and end time
- patch summary
- validation evidence

Skill repository updates are separate from OpenHarmony source edits. A
`skill-maintainer` can write this skill repo but must not write the target OH
workspace unless a separate controlled patch task authorizes it.

## High-Risk Escalation

Subagents must stop and escalate to the main Agent before recommending or
performing actions involving:

- boot chain, partitions, flashing, firmware, bootloader, or signing
- HDF service startup, driver loading, init, SELinux or permission policy
- binary replacement, closed prebuilts, kernel modules, or firmware blobs
- file deletion, mass formatting, or broad refactors
- physical device power, USB reset, or rig-controller actions
- repeated failures after two materially similar attempts

High-risk work requires explicit evidence, a patch or operation plan, and a
recorded approval path before build, flash, or device actions continue.

## Dispatch Flow

1. Main Agent creates a task spec from the user request and current evidence.
2. Deterministic tools build evidence packs whenever possible.
3. Read-only subagents run in parallel when their input sets do not conflict.
4. Main Agent reads only task outputs, evidence pack manifests, and concise
   summaries.
5. Main Agent decides whether to request more evidence, approve a patch plan,
   run tests, update the skill, or stop.
6. Reporter or skill-maintainer tasks produce handoff artifacts and update
   reusable checklists, taxonomies, schemas, or templates.

## Pilot Slice

The first v0.1 pilot should run three read-only tasks over one historical
iteration:

- `repo-surveyor` for file and module candidates
- `build-log-triager` for top build or runtime errors
- `regression-reviewer` for baseline delta and risk

The main Agent should merge only their structured outputs into a next-action
plan. It should not read full logs unless a cited excerpt is insufficient.

For the v0.2 practical playbook, read `docs/codex_subagent_playbook.md`.
