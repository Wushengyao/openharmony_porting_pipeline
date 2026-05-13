# Auxiliary Stage: Dirty Workspace Analyzer

Use skill: `openharmony_porting_aux_dirty_workspace`.


This is a fresh isolated Codex session.
Do not assume previous chat context.
Do not resume or rely on prior conversations.
Read only the input files listed in this prompt, plus source files only when the stage explicitly requires shell/git inspection.
Do not read archived failed runs or previous final reports unless explicitly listed.
Write only the required output files.
At the end, return a JSON object conforming to the provided output schema.


## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`
- `porting_knowledge_output/00_config/operator_context.md` or `.json` if present
- `porting_knowledge_output/01_raw_records/repo_status.raw.txt`
- `porting_knowledge_output/01_raw_records/dirty_repo_records.csv` if present
- `porting_knowledge_output/01_raw_records/dirty_file_records.jsonl` if present
- `porting_knowledge_output/01_raw_records/untracked_file_records.csv` if present

## Required output files

- Update or create `01_raw_records/dirty_repo_records.csv`
- Update or create `01_raw_records/dirty_file_records.jsonl`
- Update or create `01_raw_records/untracked_file_records.csv`
- Write `03_semantic_analysis/dirty_workspace_analysis.md`

## Rule

Classify dirty files as source/config/binary/generated/build_output/prebuilt_import/unknown. Do not mark dirty content as committed history.
Use operator-provided dirty-workspace policy as a hint for classification and reporting, not as committed-history evidence.

## Final JSON

Return `stage_result` JSON only in the final answer.
