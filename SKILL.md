---
name: openharmony-porting-pipeline
description: Run the Wushengyao OpenHarmony porting pipeline, also known as openharmony_porting_pipeline, to extract evidence-bound board/SoC porting knowledge, generate reusable porting skill artifacts, audit outputs, export cross-scenario meta inputs, and coordinate build-server to Windows local-device automation for OpenHarmony flashing and smoke validation.
---

# OpenHarmony Porting Pipeline

Use this Skill when asked to run, install, operate, inspect, update, or reuse
the `Wushengyao/openharmony_porting_pipeline` workflow.

Keep this file as the core contract and routing table. Load detailed references
only when the task needs them.

## Repository Map

- `tools/`: pipeline runners, deterministic extraction scripts, validators,
  aggregators, local-device helpers, and XTS/HATS runners.
- `prompts/`: isolated Codex prompts for staged analysis and execution
  assistant work.
- `schemas/`: JSON schemas for stage results, task packets, evidence packs,
  execution plans, and validation outputs.
- `docs/`: runbooks for multi-agent work, local-device automation, cross-scenario
  usage, and OH6.x RISC-V rc0 stabilization.
- `references/`: progressively loaded rules, project lessons, and formal XTS
  workflows.
- `agents/`: subagent role prompts for survey, triage, reporting, validation,
  skill maintenance, and XTS/HATS work.

## Core Rules

- Preserve evidence boundaries. Repository records, manifests, diffs, binary
  hashes, dirty workspace records, logs, screenshots, flash jobs, and xDevice
  reports are evidence; operator context is a hint.
- Keep unknowns explicit. Do not infer build, boot, runtime, provenance,
  certification, or test pass without direct evidence.
- Keep build success separate from boot and runtime success. `build.sh` passing
  is compile-flow evidence only.
- Preserve product functionality by default. Do not remove features, component
  selections, or subsystem coverage just to pass a build unless the user
  explicitly approves a diagnostic reduction.
- When binary, firmware, BSP, closed-driver, or prebuilt payloads are missing,
  prefer clearly marked compile-only fake interfaces or ELF stubs over feature
  deletion, and record replacement conditions as dependency debt.
- Use repository scripts and schemas before ad hoc extraction, parsing, or
  validation.
- Keep a single writer for each OpenHarmony source workspace. Subagents default
  to read-only task packets unless a scoped writer role is explicitly assigned.
- Stage isolation matters. Pass files, schemas, and stage result JSON between
  agents and stages, not raw chat history.
- Treat long-running porting as an iterative source-control workflow. Commit
  reliable progress in source, work-record, and skill repositories when the
  evidence is good enough to preserve.

For the detailed operating rulebook, read
`references/porting_operating_rules.md`.

## Route By Task

| Task | Read First | Primary Tools |
| --- | --- | --- |
| Run the extraction/audit pipeline | `references/pipeline_command_reference.md`, `references/stage_contract.md`, `references/evidence_rules.md` | `tools/run_pipeline.sh`, `tools/run_stage.sh`, validators |
| Dispatch subagents | `docs/agent_architecture.md`, `AGENTS.md`, `schemas/agent_task.schema.json`, `schemas/evidence_pack.schema.json`, `schemas/acceptance_state.schema.json` | role prompts under `agents/` |
| Run four-tree OH version-upgrade analysis | `references/pipeline_command_reference.md`, `docs/oh6_riscv_version_upgrade_rc0.md` | `tools/run_version_upgrade_porting.sh` |
| Apply reviewed base patches or dependency inventories | `references/porting_operating_rules.md`, `references/pipeline_command_reference.md` | `tools/apply_porting_base_patch.py` |
| Triage RISC-V build failures | `references/porting_operating_rules.md`; search `README.md` and `tools/apply_porting_base_patch.py` for exact error text | `rg`, `build.sh`, `apply_porting_base_patch.py` |
| Run local flash/HDC/serial/smoke loops | `docs/local_device_automation.md` | `tools/oh_autoctl.py` |
| Continue MusePaper2 OH6.1 work | `references/musepaper2_oh61_lessons.md`, `docs/oh6_riscv_version_upgrade_rc0.md`, then query `oh_autoctl.py profile musepaper2` | build/package scripts, `oh_autoctl.py`, records under the project work dir |
| Run formal XTS/HATS/ACTS/DCTS/SSTS | `references/openharmony_xts_formal_workflow.md` | `tools/oh_xts_xdevice_runner.py`, `tools/oh_hats_native_runner.py` |
| Aggregate cross-scenario knowledge | `references/pipeline_command_reference.md`, `docs/CROSS_SCENARIO_USAGE.md` | `tools/run_cross_scenario_aggregator.sh`, `tools/validate_meta_output.py` |
| Update this skill | system `skill-creator`, then this file and the directly relevant references | `quick_validate.py`, forward-test if practical |

Do not keep concrete device IDs, COM ports, Windows paths, WiFi credentials, or
temporary lab values in this entry file. Put reusable project lessons in
`references/musepaper2_oh61_lessons.md`, automation details in
`docs/local_device_automation.md`, and live rig values in the oh-auto profile.

## Minimal Commands

Read detailed command examples from `references/pipeline_command_reference.md`.
The shortest entry points are:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_pipeline.sh /path/to/ohos
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_stage.sh /path/to/ohos 03_statistics_qc
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_version_upgrade_porting.sh \
  --old-original /path/to/old_clean_ohos \
  --old-ported /path/to/old_ported_ohos \
  --new-original /path/to/new_clean_ohos \
  --new-workspace /path/to/new_unported_ohos
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py profile musepaper2
```

For device work, always run discovery before action:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py status
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py profile musepaper2
```

Use profile data rather than hard-coded target IDs, serial ports, baudrates,
image staging paths, or flash templates.

## OH6.x RISC-V Porting Loop

For OH6.x RISC-V version-upgrade ports, keep the loop ordered:

1. Establish four-tree evidence and migration intent.
2. Close the `build.sh` path without deleting product functions.
3. Package the image through the product script and record zip hash, size, and
   mtime.
4. Flash through oh-auto and preserve flash job evidence.
5. Reach recovery-first automation: HDC or serial can issue `reboot fastboot`
   before unattended images can strand the board.
6. Prove boot/UI with boot params, service state, screenshots, and critical
   dmesg checks.
7. Freeze `rc0` when requested before widening into full XTS/HATS unless the
   user makes formal test pass the gate.
8. Expand tests in layers, keeping noisy logs subordinate to user-visible or
   interface-level failures.

Read `docs/oh6_riscv_version_upgrade_rc0.md` before source edits or test
widening in this mode.

## Device Automation Contract

When a task enters a compile -> flash -> device-smoke -> source-fix loop, use
the Windows local OpenHarmony automation service. Do not assume HDC, serial
ports, Titan flashing, or board USB devices exist on the Linux server.

Before device operations:

1. Read `docs/local_device_automation.md`.
2. Run `oh_autoctl.py capabilities`.
3. Query the relevant profile, for example `oh_autoctl.py profile musepaper2`.
4. Run preflight before flashing.
5. Persist every `job_id`, log/event stream, image hash, and smoke result in the
   active iteration record.

Never blindly resubmit a flash after a timeout. Query the known job first and
resume logs/events.

## XTS And HATS Contract

For formal xDevice reports, use the generated suite root under
`out/<product>/suites/<suite>` or an official resource suite with matching
version and system type. Read `references/openharmony_xts_formal_workflow.md`
before downloading packages or running ACTS, ACTS-Validator, HATS, DCTS, or
SSTS.

Use `tools/oh_xts_xdevice_runner.py` for Windows-side xDevice staging and
`tools/oh_hats_native_runner.py` for native HATS binary probes. Start with a
small harmless module before widening a suite.

## Stage Order

1. `00_scope_classifier`
2. `01_repo_baseline_extractor`
3. `02_raw_record_extractor`
4. `aux_dirty_workspace`
5. `aux_binary_asset_auditor`
6. `03_statistics_qc`
7. `04_semantic_analyzer`
8. `05_case_kb_builder`
9. `06_skill_generator`
10. `07_final_auditor`
11. `08_meta_input_exporter`
12. Optional `10_porting_execution_assistant`
13. Optional `11_version_upgrade_porting`

For deeper usage details, open only the specific tool, prompt, schema, doc, or
reference needed for the user's requested stage.

## Skill Maintenance

Keep `SKILL.md` under 500 lines. Move concrete project facts, device
configuration, long command examples, historical build-pattern catalogs, and
iteration lessons into directly linked references. Avoid duplicating the same
instruction in `SKILL.md` and a reference file.

After structural skill edits, run:

```bash
python3 /home/ve/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  /home/ve/.codex/skills/openharmony_porting_pipeline
```

Forward-test with a fresh subagent when the change could affect task routing or
when a user asks for high confidence in the skill behavior.
