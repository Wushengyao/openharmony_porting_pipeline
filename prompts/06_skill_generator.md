# Stage 06: Skill Generator

Use skill: `openharmony_porting_06_skill_generator`.


This is a fresh isolated Codex session.
Do not assume previous chat context.
Do not resume or rely on prior conversations.
Read only the input files listed in this prompt, plus source files only when the stage explicitly requires shell/git inspection.
Do not read archived failed runs or previous final reports unless explicitly listed.
Write only the required output files.
At the end, return a JSON object conforming to the provided output schema.


## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`
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

The generated Skill must include applicability, non-applicability, inputs, outputs, steps, tool commands, classification taxonomy, evidence rules, case generation rules, failure handling, quality gates, examples, and anti-examples.

It must distinguish ARM-primary board/SoC, RISC-V-primary distribution, and heterogeneous auxiliary-core scenarios.

## Final JSON

Return `stage_result` JSON only in the final answer.
