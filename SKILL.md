---
name: openharmony_porting_pipeline
description: Run the Wushengyao OpenHarmony porting pipeline to extract evidence-bound board/SoC porting knowledge, generate reusable porting skill artifacts, audit outputs, and export cross-scenario meta inputs.
---

# OpenHarmony Porting Pipeline

Use this Skill when the user asks to run, install, operate, inspect, or reuse the
`Wushengyao/openharmony_porting_pipeline` workflow.

This skill directory contains the upstream repository:

- `tools/`: pipeline runners, deterministic extraction scripts, validators, and aggregators.
- `prompts/`: isolated Codex prompts for stages `00` through `08` and auxiliary stages.
- `schemas/`: JSON schemas used by stage validation.
- `docs/`, `examples/`, and `references/`: usage notes and supporting rules.

## Common Commands

Run the full pipeline on an OpenHarmony workspace:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_pipeline.sh /path/to/ohos
```

Run in human-collaboration mode:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_pipeline.sh --mode collab /path/to/ohos
```

Run one stage:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_stage.sh /path/to/ohos 03_statistics_qc
```

Run the plan-only execution assistant after the evidence pipeline:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_porting_execution_assistant.sh \
  --source-output /path/to/ohos/porting_knowledge_output \
  --meta-output /path/to/openharmony_porting_meta_output \
  /path/to/ohos
```

Aggregate multiple scenario outputs:

```bash
bash /home/ve/.codex/skills/openharmony_porting_pipeline/tools/run_cross_scenario_aggregator.sh \
  --input scenario_outputs/t113/porting_knowledge_output \
  --input scenario_outputs/ruyios/porting_knowledge_output \
  --out openharmony_porting_meta_output
```

Validate an existing cross-scenario output:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/validate_meta_output.py --out openharmony_porting_meta_output
```

## Operating Rules

- Keep stage isolation: pass files and stage results between stages, not full chat history.
- Treat repository records, diffs, manifests, binary hashes, dirty workspace records, and logs as evidence.
- Keep operator context as user-supplied hints; if it conflicts with repository evidence, record the conflict and prefer verifiable evidence.
- Preserve unknowns instead of inventing build, boot, runtime, provenance, or validation status.
- Do not promote force-sync SDK commits, initial imports, `.gitattributes`-only commits, dirty workspace files, or binary imports into reusable source-fix cases.
- In cross-scenario output, distinguish `universal_by_design` pipeline guardrails from `universal_from_evidence` case/pattern-derived methods; do not use a bare `universal` label.
- Generate and validate cross-scenario `conditional` methods in `02_patterns/conditional_methods.jsonl` with `derivation=conditional_from_evidence` when evidence clusters span multiple scenarios.
- Keep conditional method boundaries precise: HDF driver, media/camera HDF, binary/prebuilt provenance, and dirty workspace governance are separate clusters.
- Preserve direct machine traceability from meta methods to source support by emitting `meta_method_to_case` and `meta_method_to_pattern` rows.
- Keep case `scenario_type` values within the registry labels for that `scenario_id`; use `scenario_shape` for synthesized labels.
- Keep `evidence_type` / `evidence_level` separate from `evidence_strength`.
- Retain LLM refinement status files even when deterministic aggregation is used without `--llm-refine`.
- During `--llm-refine`, protect `cross_scenario_result.json` machine counts and restore deterministic output if Codex refinement fails.
- Use `porting_knowledge_output/` as the default output root unless the user specifies another directory.
- Prefer the repository scripts over hand-written ad hoc extraction or validation.
- The execution assistant is a post-pipeline layer. It defaults to plan-only,
  must not auto-generate high-risk patches or external dependency artifacts,
  and must not infer boot/runtime/test pass from build pass.

Cross-scenario aggregation now emits `meta_skill_pack/` with installable
`SKILL.md` drafts plus `_validate_meta_output.log` for the validation transcript.

## Stage Order

1. `00_scope_classifier`
2. `01_repo_baseline_extractor`
3. `02_raw_record_extractor`
4. `aux_dirty_workspace`
5. `aux_binary_asset_auditor`
6. `03_statistics_qc`
7. `04_semantic_analyzer`
8. `05_case_kb_builder`
9. `06_skill_generator`
10. `07_final_auditor`
11. `08_meta_input_exporter`
12. Optional `10_porting_execution_assistant`

For deeper usage details, read `README.md` in this skill directory first, then
open only the specific tool, prompt, schema, or reference needed for the user's
requested stage.
