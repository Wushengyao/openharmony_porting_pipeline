# Stage 08: Meta Input Exporter

This is a fresh isolated Codex session. Do not assume previous chat context. Do not read archived failed runs. Prefer the deterministic tool `tools/export_meta_inputs.py` for this stage. At the end, return JSON conforming to `stage_result.schema.json`.

## Goal

Export a single scenario's `porting_knowledge_output/` into stable cross-scenario input artifacts under:

```text
porting_knowledge_output/07_meta_inputs/
```

## Input files

- `00_config/task_profile.yaml`
- `02_statistics/statistics_summary.json`
- `04_knowledge_base/cases/*.md`
- `04_knowledge_base/patterns/*.md`
- `06_audit/final_audit_report.md`
- `06_audit/blocking_issues.md`
- `06_audit/non_blocking_issues.md`
- `_stage_results/*.json`

Do not use `05_skill_output/generated_skill.md` as universal-method evidence. It is a single-scenario skill output only.

## Required output files

- `07_meta_inputs/scenario_card.yaml`
- `07_meta_inputs/normalized_cases.jsonl`
- `07_meta_inputs/pattern_candidates.jsonl`
- `07_meta_inputs/anti_patterns.jsonl`
- `07_meta_inputs/method_fragments.jsonl`
- `07_meta_inputs/validation_status.yaml`
- `07_meta_inputs/meta_input_audit.md`

## Hard rules

1. `scenario_id` must be stable, short, and not just `t113`.
2. Unknown fields must be written as `unknown`, not invented.
3. Statistics must come from `02_statistics/statistics_summary.json`.
4. Build, boot, runtime, and tests remain `unknown` unless explicit logs are cited.
5. Single-scenario cases must not use `reuse_level=universal`; downgrade to `universal_candidate` if needed.
6. Pattern candidates are hypotheses. They must set `needs_cross_scenario_confirmation=true` unless `candidate_scope=scenario_specific`.
7. Dirty workspace, binary/prebuilt assets, initial imports, force-sync commits, and `.gitattributes`-only commits must stay separate from reusable source-fix claims.

## Required anti-pattern coverage

Export anti-pattern records for:

- force-sync commit treated as porting experience;
- `.gitattributes`-only commit treated as subsystem case;
- dirty workspace treated as committed history;
- binary/prebuilt import treated as source fix;
- RISC-V auxiliary core treated as RISC-V primary runtime;
- single-scenario case directly promoted to universal method.

## Final JSON

Return `stage_result` JSON only in the final answer.
