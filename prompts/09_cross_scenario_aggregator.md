# Stage 09: Cross-Scenario Aggregator LLM Refinement

This is a fresh isolated Codex session. Do not assume previous chat context. Do not read individual source repos. Do not read raw giant evidence files unless explicitly listed below. This stage refines already-normalized cross-scenario output, not single-scenario Markdown reports.

## Environment

The environment variable `CROSS_SCENARIO_META_OUTPUT` points to the `openharmony_porting_meta_output/` directory. If it is unset, use `openharmony_porting_meta_output/` under the current working directory.

## Allowed input files

Read only compact meta files:

- `00_scenario_registry/scenario_registry.yaml`
- `00_scenario_registry/scenario_comparison_matrix.md`
- `01_normalized_cases/cases.jsonl`
- `02_patterns/pattern_candidates.jsonl`
- `02_patterns/method_fragments.jsonl`
- `02_patterns/meta_methods.jsonl`
- `02_patterns/anti_patterns.jsonl`
- `02_patterns/universal_methods.md`
- `02_patterns/conditional_patterns.md`
- `02_patterns/case_inventory_by_scenario.md`
- `02_patterns/scenario_specific_knowledge.md`
- `02_patterns/anti_patterns.md`
- `03_methodology/*.md`
- `04_global_kb/problem_taxonomy.yaml`
- `04_global_kb/risk_taxonomy.yaml`
- `04_global_kb/path_module_ontology.md`
- `meta_report.md`

Do not read:

- `evidence_index.jsonl` if it is large;
- raw single-scenario `commit_records.jsonl`;
- raw single-scenario `binary_asset_records.csv`;
- raw single-scenario `dirty_file_records.jsonl`;
- previous chat transcripts.

## Required outputs

Update or create:

- `02_patterns/universal_methods.md`
- `02_patterns/conditional_patterns.md`
- `02_patterns/case_inventory_by_scenario.md`
- `02_patterns/scenario_specific_knowledge.md`
- `02_patterns/anti_patterns.md`
- `03_methodology/openharmony_porting_general_method.md`
- `03_methodology/board_soc_porting_runbook.md`
- `03_methodology/architecture_porting_runbook.md`
- `03_methodology/driver_hdf_porting_runbook.md`
- `03_methodology/binary_prebuilt_governance.md`
- `03_methodology/dirty_workspace_governance.md`
- `05_generated_skills/universal_openharmony_porting_skill.md`
- `05_generated_skills/arm_primary_board_soc_skill.md`
- `05_generated_skills/riscv_primary_distribution_skill.md`
- `05_generated_skills/heterogeneous_aux_core_skill.md`
- `meta_skill_pack/*/SKILL.md`
- `meta_skill_pack/references/meta_output_contract.md`
- `meta_report.md`

## Rules

1. Do not use bare `promotion_level=universal`. Use `universal_by_design` for pipeline guardrails and `universal_from_evidence` for case/pattern-derived methods.
2. Do not promote `universal_from_evidence` unless at least three distinct `scenario_id` values support it and it has at least two `source_case_ids` or `source_patterns`.
3. Do not merge ARM-primary, RISC-V-primary, and heterogeneous auxiliary-core scenarios into one undifferentiated method.
4. Each conditional pattern must include applicability and non-applicability.
5. `case_inventory_by_scenario.md` may list all cases; `scenario_specific_knowledge.md` must list only exact `reuse_level=scenario_specific` cases.
6. Anti-patterns must include risk, trigger condition and prevention.
7. Preserve traceability: every method must refer to scenario IDs, pattern IDs, case IDs, or documented evidence class.
8. Do not use single-scenario `generated_skill.md` as proof for universal methods.
9. If information conflicts across scenarios, document the conflict and turn it into a conditional rule rather than smoothing it out.
10. Do not claim build/boot/runtime/test validation unless validation_status or logs prove it.
11. Keep case `scenario_type` as a subset of the registry labels for that `scenario_id`; put synthesized labels in `scenario_shape`.
12. Keep `evidence_type` and `evidence_level` in the canonical evidence-type enum, and keep strength in `evidence_strength`.
13. Installable skills must be written as `SKILL.md` files with frontmatter, input/output contract, case selector, tool commands, failure handling, and quality gates.

## Validator Contract Terms

The final Markdown is validated by `tools/validate_meta_output.py`. Preserve these exact terms even when the surrounding prose is refined:

- `02_patterns/conditional_patterns.md` must contain the exact terms `ARM-primary`, `RISC-V-primary`, and `heterogeneous_aux_core`.
- `02_patterns/anti_patterns.md` must contain the exact terms `dirty`, `binary`, `force-sync`, `.gitattributes`, and `RISC-V`.
- `meta_report.md` must contain the exact reuse class terms `universal_by_design`, `universal_from_evidence`, `universal_candidate`, `conditional`, `scenario_specific`, `risk_only`, and `anti_pattern`.
- If the scenario count is less than 3, `02_patterns/universal_methods.md` must contain the exact heading or sentence `No Formal Universal Methods Promoted`.
- Preserve `global_method_fragment_id` values when referencing method fragments; local `method_fragment_id` values are not globally unique across scenarios.
- Keep evidence traceability compact: refer to `evidence_ref` values rather than pasting full evidence blobs into prose.
- `meta_skill_pack/*/SKILL.md` files must keep YAML frontmatter with `name` and `description`.
- Do not replace `universal_by_design` / `universal_from_evidence` with a bare `universal` label.

These terms are contract markers, not optional wording. Do not replace them with synonyms such as "RISC-V Primary", "risk-only", or "none promoted".

## Final JSON

Return JSON conforming to `stage_result.schema.json` with status, summary, input_files_read, output_files_written, blocking_issues, non_blocking_issues, and next_stage_inputs.
