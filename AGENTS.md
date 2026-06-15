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
- Do not promote native HATS subset pass to formal xDevice pass.
- Do not promote build pass to boot, runtime, test, or release pass.
- Preserve unknowns instead of inventing status.
