# Stage 04: Semantic Analyzer

Use skill: `openharmony_porting_04_semantic_analyzer`.


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
- `porting_knowledge_output/01_raw_records/diffs/`
- `porting_knowledge_output/03_semantic_analysis/evidence_index.jsonl`
- `porting_knowledge_output/02_statistics/statistics_summary.json`

## Required output files

- `03_semantic_analysis/commit_analysis.jsonl`
- `03_semantic_analysis/repo_analysis/*.md`
- `03_semantic_analysis/subsystem_analysis/*.md`
- `03_semantic_analysis/risk_items.md`
- `03_semantic_analysis/workaround_items.md`

## Coverage guidance

For T113-like projects, prioritize device/board, device/soc, vendor, drivers, kernel, bootloader, WiFi, HDF Audio, binary/prebuilt, and dirty workspace.

For RuyiOS/riscv64 projects, prioritize vendor/product, device/board, device/soc, kernel, prebuilts/toolchain, OpenSBI/U-Boot, third_party architecture compatibility.

## Evidence rule

Every non-trivial claim must cite commit/file/diff/dirty/binary evidence. If missing, mark as `unknown` or `inference`.

## Final JSON

Return `stage_result` JSON only in the final answer.
