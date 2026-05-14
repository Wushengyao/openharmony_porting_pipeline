# Stage 09: Cross-Scenario Aggregator

This stage reads multiple single-scenario `07_meta_inputs/` directories and produces a global OpenHarmony porting method library. Prefer the deterministic entrypoint:

```bash
bash tools/run_cross_scenario_aggregator.sh --input <porting_knowledge_output> --input <porting_knowledge_output> --out openharmony_porting_meta_output
```

or:

```bash
bash tools/run_cross_scenario_aggregator.sh --input-root scenario_outputs --out openharmony_porting_meta_output
```

## Inputs

Each input must already contain:

- `07_meta_inputs/scenario_card.yaml`
- `07_meta_inputs/normalized_cases.jsonl`
- `07_meta_inputs/pattern_candidates.jsonl`
- `07_meta_inputs/anti_patterns.jsonl`
- `07_meta_inputs/method_fragments.jsonl`
- `07_meta_inputs/validation_status.yaml`

If an input lacks `07_meta_inputs`, stop and tell the operator to run `08_meta_input_exporter`. Do not parse old Markdown-only outputs for aggregation.

## Required outputs

- `00_scenario_registry/scenario_registry.yaml`
- `00_scenario_registry/scenario_comparison_matrix.md`
- `01_normalized_cases/cases.jsonl`
- `02_patterns/universal_methods.md`
- `02_patterns/conditional_patterns.md`
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
- `meta_report.md`

## Promotion rules

- Formal `universal` requires at least three distinct `scenario_id` values.
- If fewer than three scenarios are supplied, write only `universal_candidate`, `conditional`, `scenario_specific`, `risk_only`, and `anti_pattern`.
- `conditional` patterns must name applicability and non-applicability, such as ARM-primary board/SoC, RISC-V-primary distribution, heterogeneous auxiliary-core, HDF/driver chain, binary/prebuilt governance, or dirty workspace governance.
- Scenario-specific knowledge such as BK7236, T113 speaker PA pins, vendor directory shapes, and concrete firmware blobs must remain scenario-specific.
- Preserve traceability: method -> pattern -> case -> scenario -> evidence.

## Safety

Do not load large `evidence_index.jsonl`, binary CSVs, dirty JSONL, or full diffs into context. Use compact normalized inputs only.
