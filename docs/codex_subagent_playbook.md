# Codex Subagent Playbook

This playbook describes the practical v0.2 workflow for using Codex native
subagents with the OpenHarmony porting pipeline.

## Operating Shape

The main Agent keeps ownership of:

- task decomposition
- evidence judgment
- risk decisions
- writer-lock ownership
- patch merge decisions
- acceptance or waiver claims

Subagents receive bounded task packets. They return structured outputs and
evidence references. They do not make release claims.

## Minimal Read-Only Pilot

Use this pilot before allowing writer tasks in a new project:

1. Build an evidence pack from the current iteration.
2. Create three task directories from `examples/agent_tasks/`.
3. Dispatch `repo-surveyor`, `build-log-triager`, and `regression-reviewer`.
4. Read only their outputs and the evidence pack manifest.
5. Produce a next-action plan or a patch-planner task.

A pilot is not complete merely because subagents were spawned. Persist every
subagent result under its task `outputs/` directory, validate each `task.yaml`
against `schemas/agent_task.schema.json`, validate the evidence pack manifest
against `schemas/evidence_pack.schema.json`, and write a merged main-Agent plan.
Transient chat notifications are useful coordination signals, but they are not
auditable project artifacts until copied into the task directory.

Recommended directory shape:

```text
agent_tasks/pilot-iterationNNN/
  repo-survey/task.yaml
  build-log-triage/task.yaml
  baseline-regression/task.yaml
  merged_next_plan.md
```

## Tool-First Evidence Pack

Start from deterministic tools:

```bash
python3 tools/evidence_pack_builder.py \
  --out-dir evidence_packs/iterationNNN \
  --job-id iterationNNN \
  --iteration NNN \
  --board musepaper2 \
  --os-version OH6.1-Release \
  --arch riscv64 \
  --source-root /path/to/ohos \
  --build-log /path/to/build.log \
  --serial-log /path/to/serial.log
```

When a log is large, slice it before giving it to a subagent:

```bash
python3 tools/log_slice.py \
  --log /path/to/build.log \
  --taxonomy taxonomies/build_error_taxonomy.yaml \
  --out-dir agent_tasks/pilot-iterationNNN/build-log-triage/inputs/log_slices
```

## Dispatch Rules

- Use read-only subagents for survey, triage, regression review, reporting, and
  runtime/HDF review.
- Use `device-automation-steward` only through approved device tools.
- Use `patch-planner` before `patch-writer`.
- Use `patch-writer` only with an explicit writer lock and path whitelist.
- Use `skill-maintainer` for this skill repository, not for OpenHarmony source.

Do not delegate the immediate blocking task if the main Agent must decide it
right now. Delegate sidecar tasks that can run while the main Agent continues
non-overlapping work.

## Writer Task Gate

Before any OpenHarmony source write:

```bash
python3 tools/diff_risk_scanner.py --repo /path/to/ohos --out risk_scan.yaml
python3 tools/secret_and_binary_scanner.py --repo /path/to/ohos --out secret_binary_scan.yaml
```

The main Agent must review:

- approved `patch_plan.yaml`
- `policies/path_whitelist.yaml`
- `policies/risk_policy.yaml`
- current dirty workspace summary
- writer-lock record
- validation plan

High-risk findings require an approval record before build, flash, or device
operations continue.

## Merging Subagent Results

The main Agent should merge only:

- machine-readable outputs from task `outputs/`
- `evidence_packs/<id>/manifest.yaml`
- concise summaries such as `top_errors.md`
- risk and waiver ledgers

Raw logs are read only when the cited excerpt is ambiguous or the parser itself
is suspected.

## Closeout

Every meaningful iteration should end with:

- updated acceptance state
- known debts or waivers
- validation command summary
- skill-maintainer update when a new reusable rule, taxonomy, checklist, or
  tool behavior was learned
