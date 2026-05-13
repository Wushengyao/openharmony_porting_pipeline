# Stage 01: Repo Baseline Extractor

Use skill: `openharmony_porting_01_repo_baseline_extractor`.


This is a fresh isolated Codex session.
Do not assume previous chat context.
Do not resume or rely on prior conversations.
Read only the input files listed in this prompt, plus source files only when the stage explicitly requires shell/git inspection.
Do not read archived failed runs or previous final reports unless explicitly listed.
Write only the required output files.
At the end, return a JSON object conforming to the provided output schema.


## Input files

- `porting_knowledge_output/00_config/task_profile.yaml`

## Required actions

1. Create manifest snapshots if possible:
   - `00_config/downstream_manifest_snapshot.xml`
   - `00_config/baseline_manifest_snapshot.xml` if resolvable
2. Generate:
   - `00_config/repo_revision_map.csv`
   - `01_raw_records/repo_list.csv`
   - `01_raw_records/repo_status.raw.txt`
   - `01_raw_records/baseline_resolution_report.md`
3. Use `repo list`, `repo manifest -r`, `repo forall`, and git commands when available.
4. If baseline cannot be resolved, mark `baseline_status=baseline_unknown`; do not fabricate upstream revisions.
5. Dirty repo status must be captured.

## Final JSON

Return `stage_result` JSON only in the final answer.
