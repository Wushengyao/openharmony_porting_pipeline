# Stage 03: Statistics QC

Use skill: `openharmony_porting_03_statistics_qc`.


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
- `porting_knowledge_output/00_config/repo_revision_map.csv`
- `porting_knowledge_output/01_raw_records/commit_records.jsonl`
- `porting_knowledge_output/01_raw_records/file_change_records.jsonl`
- `porting_knowledge_output/01_raw_records/binary_asset_records.csv`
- `porting_knowledge_output/01_raw_records/dirty_repo_records.csv`
- `porting_knowledge_output/01_raw_records/dirty_file_records.jsonl`

## Required output files

- `02_statistics/statistics_summary.json`
- `02_statistics/statistics_summary.md`
- `02_statistics/repo_change_distribution.csv`
- `02_statistics/file_type_distribution.csv`
- `02_statistics/subsystem_distribution.csv`
- `02_statistics/binary_asset_summary.md`
- `02_statistics/qc_report.md`

## Hard rule

All counts must be computed from raw records. `statistics_summary.json` is the authoritative count source for later stages.
Operator context must not change numeric counts.

## Final JSON

Return JSON conforming to `statistics_summary.schema.json` in the final answer. Also write the stage files above.
