# Stage 07: Final Auditor

Use skill: `openharmony_porting_07_final_auditor`.


This is a fresh isolated Codex session.
Do not assume previous chat context.
Do not resume or rely on prior conversations.
Read only the input files listed in this prompt, plus source files only when the stage explicitly requires shell/git inspection.
Do not read archived failed runs or previous final reports unless explicitly listed.
Write only the required output files.
At the end, return a JSON object conforming to the provided output schema.


## Input files

Read all files under `porting_knowledge_output/` except archived failed runs.

## Required output files

- `06_audit/final_audit_report.md`
- `06_audit/blocking_issues.md`
- `06_audit/non_blocking_issues.md`
- `06_audit/artifact_manifest.json`

## Audit checks

1. Statistics match raw records.
2. `task_profile.yaml` scenario is not contradicted by generated outputs.
3. `repo_analysis/` and `subsystem_analysis/` are non-empty.
4. Cases cite commits/files that exist in raw records.
5. Binary asset claims cite binary records.
6. Dirty workspace is separately represented.
7. Generated Skill is complete, not a short summary.
8. Workarounds are not presented as best practices.

## Final JSON

Return JSON conforming to `audit_result.schema.json` in the final answer. Also write audit files.
