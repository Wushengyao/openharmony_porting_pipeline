# Stage 07: Final Auditor

Use skill: `openharmony_porting_07_final_auditor`.

This is a fresh isolated Codex session. Do not assume previous chat context. Do not resume or rely on prior conversations. Read all files under `porting_knowledge_output/` except archived failed runs. Write only the required output files. At the end, return JSON conforming to `audit_result.schema.json`.

## Required output files

- `06_audit/final_audit_report.md`
- `06_audit/blocking_issues.md`
- `06_audit/non_blocking_issues.md`
- `06_audit/artifact_manifest.json`

## Audit checks

1. Statistics match raw records.
2. `task_profile.yaml` scenario is not contradicted by generated outputs.
3. `repo_analysis/` is non-empty and `subsystem_analysis/` contains feature-level files beyond coarse classification buckets.
4. Cases cite commits/files that exist in raw records using the canonical `evidence:` schema; there must not be a separate `Validator Evidence` block.
5. Cases are not based only on force-sync, `.gitattributes`, or initial-import evidence.
6. Case titles match evidence paths and subjects.
7. HDF/Audio, WiFi, Boot/Firmware, Product/Board/SoC cases have matching subsystem evidence.
8. Binary asset claims cite binary records with path and sha256.
9. Dirty workspace is separately represented and not called committed history.
10. Generated Skill is complete, not a short summary.
11. `agent_runbook.md`, `next_porting_task_template.md`, and `quality_checklist.md` are substantive enough for a fresh agent.
12. Workarounds are not presented as best practices.
13. T113 ARM-primary + auxiliary-core profile is not silently rewritten as RISC-V-primary.
14. Canonical `_codex_stage_logs/<stage>.validation.log` files for passed stages contain no `[BLOCKED]` or `validation failed`; failed attempts, if any, must live under `_codex_stage_logs/_failed_attempts/`.
15. Every source path mentioned in case bodies resolves to `file_change_records.jsonl` or `dirty_file_records.jsonl`; unsupported paths are blocking unless clearly marked `unknown`.
16. `commit_analysis.jsonl` must not mark `initial_import`, `.gitattributes`-only, or unproven `force sync sdk code` commits as `is_case_candidate=true`.
17. Dirty/binary samples attached to a case or feature must match by repo, path prefix, or strong theme keyword; broad classification-only matches are non-blocking at minimum and blocking if used as primary evidence.

## Blocking examples

- An HDF Audio case whose evidence is only `foundation/*.gitattributes`.
- A Boot/Firmware case whose evidence is only `applications/*.gitattributes`.
- A case containing “force sync sdk code” as the main evidence.
- `agent_runbook.md` under 1500 characters.
- `quality_checklist.md` under 1200 characters.
- Final report says “accept” while any blocking condition exists.
- Final report says “accept” while canonical validation logs still contain failed attempts.
- A case body references a concrete file path that is absent from raw/dirty records.
- A `force sync sdk code` commit remains `is_case_candidate=true` without explicit non-`.gitattributes` board/SoC/driver/build proof.

`blocking_issues.md` must contain exactly `- None` when there are no blocking issues; do not use prose such as “No blocking issues found.”

## Final JSON

Return JSON conforming to `audit_result.schema.json` in the final answer. Also write audit files.
