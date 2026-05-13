# Stage 02: Raw Record Extractor

Use skill: `openharmony_porting_02_raw_record_extractor`.


This is a fresh isolated Codex session.
Do not assume previous chat context.
Do not resume or rely on prior conversations.
Read only the input files listed in this prompt, plus source files only when the stage explicitly requires shell/git inspection.
Do not read archived failed runs or previous final reports unless explicitly listed.
Write only the required output files.
At the end, return a JSON object conforming to the provided output schema.


## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`
- `porting_knowledge_output/00_config/repo_revision_map.csv`
- `porting_knowledge_output/01_raw_records/repo_list.csv`
- `porting_knowledge_output/01_raw_records/repo_status.raw.txt`

## Required output files

- `porting_knowledge_output/01_raw_records/commit_records.jsonl`
- `porting_knowledge_output/01_raw_records/file_change_records.jsonl`
- `porting_knowledge_output/01_raw_records/binary_asset_records.csv`
- `porting_knowledge_output/01_raw_records/dirty_repo_records.csv`
- `porting_knowledge_output/01_raw_records/dirty_file_records.jsonl`
- `porting_knowledge_output/01_raw_records/untracked_file_records.csv`
- `porting_knowledge_output/01_raw_records/diffs/`
- `porting_knowledge_output/03_semantic_analysis/evidence_index.jsonl`

## Extraction rules

- Separate `initial_import`, `post_import_change`, `downstream_unique`, `baseline_unknown`, and `dirty_workspace`.
- For every non-initial, non-merge commit, write file-change records.
- For binary/prebuilt files, write binary records with size and sha256 when possible.
- For dirty workspace, write dirty records separately; do not merge them into committed facts.
- Do not write final_report.md or cases.

## Final JSON

Return `stage_result` JSON only in the final answer.
