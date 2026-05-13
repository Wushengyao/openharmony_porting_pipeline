# Auxiliary Stage: Binary Asset Auditor

Use skill: `openharmony_porting_aux_binary_asset_auditor`.


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
- `porting_knowledge_output/01_raw_records/binary_asset_records.csv` if present
- `porting_knowledge_output/01_raw_records/file_change_records.jsonl`
- `porting_knowledge_output/01_raw_records/dirty_file_records.jsonl` if present

## Required output files

- Update or create `01_raw_records/binary_asset_records.csv`
- Write `04_knowledge_base/binary_asset_index.md`
- Write `04_knowledge_base/binary_risk_report.md`

## Human collaboration context

Use operator-provided binary provenance/licensing hints only as review context unless they are backed by file metadata, hashes, manifests, licenses, or source/build recipes.

## Required fields

`path,size,sha256,file_type,architecture,possible_usage,source_commit,introduced_by,license_risk,redistribution_risk,runtime_dependency,analysis_note`

## Final JSON

Return `stage_result` JSON only in the final answer.
