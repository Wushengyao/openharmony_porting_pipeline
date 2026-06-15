# Agent Rules

These rules apply to Agents working in this skill repository or using this
repository to coordinate OpenHarmony porting work.

## Main Agent

- Own task decomposition, evidence judgment, risk decisions, patch merge
  decisions, and final acceptance claims.
- Read evidence packs and structured subagent outputs before reading raw logs.
- Keep build, package, flash, boot, HDC, UI, subsystem smoke, HATS native,
  xDevice formal, and release acceptance as separate gates.
- Record every RC or release claim with evidence paths, commands, hashes,
  screenshots, report files, or log offsets.
- Hold the writer lock before allowing any Agent to modify an OpenHarmony
  source workspace.

## Subagents

- Default sandbox is read-only.
- Use `schemas/agent_task.schema.json` for every task spec.
- Write structured outputs first; Markdown summaries are secondary.
- Cite evidence paths and offsets instead of copying full raw logs.
- Stop and escalate to the main Agent on high-risk paths or operations.
- Route model and budget choices through `policies/model_routing.yaml` and
  `policies/budget_policy.yaml`.

## Output Formats

- Survey tasks produce `repo_survey.yaml`, `file_candidates.md`, and
  `evidence_refs.md`.
- Log/runtime triage tasks produce structured findings plus `top_errors.md` or
  `runtime_review.md`.
- Test tasks produce `test_summary.yaml`, `failures_by_subsystem.yaml`, and
  `rerun_plan.yaml`.
- Regression tasks produce `regression_matrix.yaml` and `risk_items.yaml`.
- Device tasks produce `device_job_ledger.yaml`, `device_state.yaml`, and
  optional `recovery_plan.yaml`.
- Writer tasks produce `patch_summary.md`, `changed_files.yaml`, and
  `validation_requested.yaml`.
- Reports must link to evidence packs and acceptance state files.

## Writer Policy

- Only one writer Agent may touch a single OpenHarmony workspace at a time.
- `patch-writer` writes require an explicit task, path whitelist, writer lock,
  diff summary, and validation plan.
- `skill-maintainer` may write this skill repository but must not write the
  OpenHarmony source workspace.
- Do not delete, move, or mass-format files outside the task scope.

## High-Risk Operations

Escalate before work involving:

- boot chain, partitions, firmware, bootloader, signing, or flashing
- HDF service startup, driver loading, init, SELinux, or permission policy
- binary replacement, prebuilts, kernel modules, firmware blobs, or closed
  driver assets
- physical power, USB reconnect, rig-controller, or repeated device recovery
- waivers, RC acceptance, release acceptance, or customer-facing claims

## Evidence Discipline

- Prefer deterministic tools for build/test/log/device operations.
- Keep raw artifacts under artifact roots and expose compact evidence packs.
- Use `tools/evidence_pack_builder.py`, `tools/log_slice.py`,
  `tools/diff_risk_scanner.py`, `tools/secret_and_binary_scanner.py`,
  `tools/device_job_ledger.py`, and `tools/recovery_plan_builder.py` before
  asking the main Agent to read noisy artifacts.
- Do not promote native HATS subset pass to formal xDevice pass.
- Do not promote build pass to boot, runtime, test, or release pass.
- Preserve unknowns instead of inventing status.
