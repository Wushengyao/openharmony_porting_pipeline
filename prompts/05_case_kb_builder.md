# Stage 05: Case KB Builder

Use skill: `openharmony_porting_05_case_kb_builder`.


This is a fresh isolated Codex session.
Do not assume previous chat context.
Do not resume or rely on prior conversations.
Read only the input files listed in this prompt, plus source files only when the stage explicitly requires shell/git inspection.
Do not read archived failed runs or previous final reports unless explicitly listed.
Write only the required output files.
At the end, return a JSON object conforming to the provided output schema.


## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`
- `porting_knowledge_output/01_raw_records/commit_records.jsonl`
- `porting_knowledge_output/01_raw_records/file_change_records.jsonl`
- `porting_knowledge_output/01_raw_records/dirty_file_records.jsonl`
- `porting_knowledge_output/01_raw_records/binary_asset_records.csv`
- `porting_knowledge_output/03_semantic_analysis/commit_analysis.jsonl`
- `porting_knowledge_output/03_semantic_analysis/repo_analysis/`
- `porting_knowledge_output/03_semantic_analysis/subsystem_analysis/`
- `porting_knowledge_output/03_semantic_analysis/risk_items.md`
- `porting_knowledge_output/03_semantic_analysis/workaround_items.md`

## Required output files

- `04_knowledge_base/cases/*.md`
- `04_knowledge_base/patterns/*.md`
- `04_knowledge_base/path_module_index.md`
- `04_knowledge_base/board_soc_porting_rules.md`
- `04_knowledge_base/workaround_items.md`

## Case evidence gate

Every case must include a YAML-like evidence block with commits/files/diffs and must state applicability/non-applicability. Do not create cases without evidence.

## Final JSON

Return `stage_result` JSON only in the final answer.
