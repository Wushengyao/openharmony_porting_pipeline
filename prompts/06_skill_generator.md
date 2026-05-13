# Stage 06: Skill Generator

Use skill: `openharmony_porting_06_skill_generator`.

This is a fresh isolated Codex session. Do not assume previous chat context. Do not resume or rely on prior conversations. Read only the input files listed here. Do not read archived failed runs or previous final reports unless explicitly listed. Write only the required output files. At the end, return a JSON object conforming to `stage_result.schema.json`.

## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`
- `porting_knowledge_output/00_config/operator_context.md` or `.json` if present
- `porting_knowledge_output/02_statistics/statistics_summary.json`
- `porting_knowledge_output/03_semantic_analysis/repo_analysis/`
- `porting_knowledge_output/03_semantic_analysis/subsystem_analysis/`
- `porting_knowledge_output/04_knowledge_base/cases/`
- `porting_knowledge_output/04_knowledge_base/patterns/`
- `porting_knowledge_output/04_knowledge_base/board_soc_porting_rules.md`
- `porting_knowledge_output/04_knowledge_base/binary_asset_index.md` if present

## Required output files

- `05_skill_output/generated_skill.md`
- `05_skill_output/agent_runbook.md`
- `05_skill_output/next_porting_task_template.md`
- `05_skill_output/quality_checklist.md`

## Required content

The generated Skill must include:

- applicability;
- non-applicability;
- inputs;
- outputs;
- execution workflow;
- all-auto and human-collaboration operating modes;
- tool commands;
- classification taxonomy;
- evidence rules;
- case generation rules;
- failure handling;
- quality gates;
- examples;
- anti-examples.

It must distinguish ARM-primary board/SoC, RISC-V-primary distribution, and heterogeneous auxiliary-core scenarios. It must explicitly say that T113-style ARM-primary projects should not be reclassified as RISC-V-primary because auxiliary firmware exists.
It must also state that the generated Skill is not T113-only: concrete board/SoC names come from `task_profile.yaml`, raw records, cases, and optional operator context.

## Supporting file minimums

- `agent_runbook.md` must be actionable and include start procedure, evidence handling, validation commands and failure handling.
- `next_porting_task_template.md` must include target definition, inputs, scenario classification, stage plan, risk table and daily record format.
- `quality_checklist.md` must include scope, raw records, statistics, semantic analysis, cases, Skill output and audit checks.

## Final JSON

Return `stage_result` JSON only in the final answer.
