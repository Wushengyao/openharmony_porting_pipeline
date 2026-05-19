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

Single-scenario outputs may produce `universal_candidate`, but formal `universal` methods require at least three distinct scenarios and successful validation.

## 6. Traceability Notes

The aggregated `02_patterns/method_fragments.jsonl` includes `global_method_fragment_id` because single-scenario exporters may reuse local IDs such as `MF-CASE-001`.

`04_global_kb/evidence_trace_index.jsonl` is intentionally slim: it uses `trace_id` and `evidence_ref` links into `04_global_kb/evidence_index.jsonl` instead of embedding full evidence in every trace row.
