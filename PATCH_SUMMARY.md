# Patch Summary: Improve semantic/case/skill/audit quality

This patch is based on the latest T113 run review.  The previous run proved that stage isolation, raw extraction, statistics, dirty workspace and binary auditing are effective, but Phase 4-7 were too deterministic/template-driven.

## Changes

### `tools/run_stage.sh`

- Keeps `03_statistics_qc` deterministic by default.
- Changes `04_semantic_analyzer`, `05_case_kb_builder`, `06_skill_generator`, and `07_final_auditor` to LLM execution by default.
- Keeps deterministic fallback via env flags.
- Logs deterministic flags at each run.

### `tools/generate_semantic_analysis.py`

- Adds sync/noise filtering.
- Marks `initial_import`, `force sync sdk code`, `.gitattributes`-only and doc-only commits as non-case candidates.
- Adds `is_case_candidate`, `case_candidate_score`, `noise_reason`, and `_llm_inputs` candidate files.
- Prevents `.gitattributes` commits from becoming HDF/WiFi/Boot/Product cases.

### `tools/generate_case_kb.py`

- Generates fewer, higher-quality cases.
- Excludes initial import/sync/noise commits.
- Writes full case sections: problem, root cause, fix pattern, reusable rule, applicability, non-applicability, verification, risks, confidence.
- Adds rejected/noise, dirty workspace, and binary provenance patterns.

### `tools/generate_skill_output.py`

- Generates substantive `generated_skill.md`, `agent_runbook.md`, `next_porting_task_template.md`, and `quality_checklist.md`.
- Explicitly separates ARM-primary, RISC-V-primary, and heterogeneous auxiliary-core scenarios.

### `tools/run_final_audit.py`

- Adds semantic audit checks for case quality and title/evidence consistency.
- Blocks force-sync/.gitattributes-only cases.
- Blocks tiny runbook/template/checklist outputs.
- Blocks T113 ARM-primary profile contradictions.
- Skips hashing very large artifacts in manifest to avoid slow audits.

### `tools/validate_stage.py`

- Strengthens stage 05-07 hard gates.
- Blocks template cases and weak supporting files.
- Fails validation if final audit reports blocking issues.

### `prompts/04-07_*.md`

- Prompts now explicitly require LLM semantic interpretation and strict exclusions.
- Auditing prompt now includes the exact failure modes observed in the latest run.

## Rerun

```bash
bash tools/run_stage.sh "$PWD" 04_semantic_analyzer porting_knowledge_output
bash tools/run_stage.sh "$PWD" 05_case_kb_builder porting_knowledge_output
bash tools/run_stage.sh "$PWD" 06_skill_generator porting_knowledge_output
bash tools/run_stage.sh "$PWD" 07_final_auditor porting_knowledge_output
```

Use deterministic fallback only when debugging:

```bash
DETERMINISTIC_SEMANTIC_ANALYZER=1 bash tools/run_stage.sh "$PWD" 04_semantic_analyzer porting_knowledge_output
```
