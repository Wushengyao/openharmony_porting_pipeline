# Cross-Scenario Meta KB Usage

## 1. Export One Scenario As Meta Inputs

After a normal single-scenario run finishes, export compact meta inputs:

```bash
bash tools/run_stage.sh "$PWD" 08_meta_input_exporter porting_knowledge_output
```

Generated files:

```text
porting_knowledge_output/07_meta_inputs/scenario_card.yaml
porting_knowledge_output/07_meta_inputs/normalized_cases.jsonl
porting_knowledge_output/07_meta_inputs/pattern_candidates.jsonl
porting_knowledge_output/07_meta_inputs/anti_patterns.jsonl
porting_knowledge_output/07_meta_inputs/method_fragments.jsonl
porting_knowledge_output/07_meta_inputs/validation_status.yaml
porting_knowledge_output/07_meta_inputs/meta_input_audit.md
```

## 2. Run Full Pipeline And Export Meta Inputs

```bash
bash tools/run_pipeline.sh --export-meta /path/to/oh_workspace
```

Equivalent:

```bash
PIPELINE_EXPORT_META=1 bash tools/run_pipeline.sh /path/to/oh_workspace
```

Skip Stage 08 explicitly:

```bash
bash tools/run_pipeline.sh --no-export-meta /path/to/oh_workspace
```

## 3. Aggregate Multiple Scenarios

```bash
bash tools/run_cross_scenario_aggregator.sh \
  --input scenario_outputs/t113/porting_knowledge_output \
  --input scenario_outputs/ruyios/porting_knowledge_output \
  --out openharmony_porting_meta_output
```

Or discover from a root directory:

```bash
bash tools/run_cross_scenario_aggregator.sh \
  --input-root scenario_outputs \
  --out openharmony_porting_meta_output
```

For shareable packages that should not expose absolute local paths:

```bash
bash tools/run_cross_scenario_aggregator.sh \
  --input-root scenario_outputs \
  --out openharmony_porting_meta_output \
  --redact-local-paths
```

## 4. Optional LLM Refinement

```bash
bash tools/run_cross_scenario_aggregator.sh \
  --input-root scenario_outputs \
  --out openharmony_porting_meta_output \
  --llm-refine
```

## 5. Key Rule

Single-scenario outputs may produce `universal_candidate`, but formal promotion must use explicit levels:

- `universal_by_design`: pipeline guardrails such as evidence-class separation, scenario scope authority, and validation separation. These are not source-fix methods derived from cases.
- `universal_from_evidence`: case/pattern-derived methods with at least three distinct scenarios, at least two source cases or patterns, and scenario-type or SoC/vendor diversity.

Do not use a bare `universal` label.

The aggregator also normalizes case evidence fields:

- `evidence_type` / `evidence_level`: `commit_file_diff`, `commit_file`, `dirty_or_binary_only`, `log_verified`, or `unknown`.
- `evidence_strength`: `high`, `medium_high`, `medium`, `medium_low`, `low`, or `unknown`.

Case `scenario_type` values must be registry-defined labels for the same `scenario_id`; synthesized labels belong in `scenario_shape`.

The aggregator generates machine-readable cross-scenario conditional methods:

```text
02_patterns/conditional_methods.jsonl
```

Each conditional method is also present in `02_patterns/meta_methods.jsonl` with:

```text
promotion_level: conditional
derivation: conditional_from_evidence
```

Current deterministic clusters include HDF driver, media/camera HDF, WiFi/SDIO/wireless, RISC-V build/runtime/product route, boot/firmware/provenance, binary/prebuilt provenance, and dirty workspace governance.

## 6. Traceability Notes

The aggregated `02_patterns/method_fragments.jsonl` includes `global_method_fragment_id` because single-scenario exporters may reuse local IDs such as `MF-CASE-001`.

`04_global_kb/evidence_trace_index.jsonl` is intentionally slim: it uses `trace_id` and `evidence_ref` links into `04_global_kb/evidence_index.jsonl` instead of embedding full evidence in every trace row. It includes explicit `meta_method_to_case` and `meta_method_to_pattern` rows so machine audits do not have to infer meta-method support from `meta_methods.jsonl` alone.

## 7. Installable Meta Skill Pack

Cross-scenario aggregation emits installable Skill drafts:

```text
openharmony_porting_meta_output/meta_skill_pack/
|-- universal_openharmony_porting/SKILL.md
|-- arm_primary_board_soc/SKILL.md
|-- riscv_primary_distribution/SKILL.md
|-- heterogeneous_aux_core/SKILL.md
|-- references/
|-- schemas/
|-- examples/
`-- install.sh
```

The validation transcript is retained as `_validate_meta_output.log` in the output directory.
LLM refinement status is always retained as `_llm_refine_result.json`, `_llm_refine.ndjson`, and `_codex_logs/09_cross_scenario_refine.*`; deterministic runs write an explicit skip marker.
During `--llm-refine`, the runner protects `cross_scenario_result.json` machine counts and restores deterministic output if the Codex refine process fails.

The validator requires release-grade runbook sections and expanded Skill contracts, including applicability, non-applicability, inputs, outputs, workflow, evidence rules, failure handling, quality gates, examples, and anti-examples.
