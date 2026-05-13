# OpenHarmony Porting Pipeline

Evidence-bound pipeline for extracting reusable OpenHarmony board/SoC porting knowledge from a repo-managed workspace.

## Goal

The pipeline classifies the porting scenario, extracts repo and raw change records, audits dirty workspace and binary assets, computes statistics, builds semantic and case knowledge, generates a reusable Skill, and runs a final audit.

The design goal is **stage isolation**: each stage has its own Codex context and passes only files, summaries and stage results to the next stage.

## Typical Usage

```bash
bash tools/run_pipeline.sh /path/to/ohos
```

Run one stage:

```bash
bash tools/run_stage.sh /path/to/ohos 03_statistics_qc
```

The default output directory is:

```text
/path/to/ohos/porting_knowledge_output
```

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

## Deterministic and LLM Stages

The data-heavy stages are deterministic by default where repeatability is more important than prose quality:

- `03_statistics_qc`: `tools/aggregate_stats.py`

The semantic stages now default to Codex/LLM execution because prior T113 runs showed deterministic templates were structurally complete but semantically shallow:

- `04_semantic_analyzer`
- `05_case_kb_builder`
- `06_skill_generator`
- `07_final_auditor`

Deterministic fallbacks are still available for debugging or environments without model access:

```bash
DETERMINISTIC_SEMANTIC_ANALYZER=1 bash tools/run_stage.sh /path/to/ohos 04_semantic_analyzer
DETERMINISTIC_CASE_KB=1 bash tools/run_stage.sh /path/to/ohos 05_case_kb_builder
DETERMINISTIC_SKILL_GENERATOR=1 bash tools/run_stage.sh /path/to/ohos 06_skill_generator
DETERMINISTIC_FINAL_AUDIT=1 bash tools/run_stage.sh /path/to/ohos 07_final_auditor
```

Force model execution for statistics if needed:

```bash
DETERMINISTIC_STATISTICS_QC=0 bash tools/run_stage.sh /path/to/ohos 03_statistics_qc
```

## Evidence Rules

- Commit claims cite `repo_path + commit_hash`.
- File claims cite `repo_path + file_path`.
- Binary claims cite `path + sha256`.
- Dirty workspace evidence is separate from committed history.
- Statistics are copied from `02_statistics/statistics_summary.json`.
- Initial import, force-sync SDK commits and `.gitattributes`-only commits must not become reusable cases.
- T113-style ARM-primary + auxiliary-core profiles must not be silently rewritten as RISC-V-primary.

## Quality Gates

The validator and final auditor now block:

- statistics/raw-record count mismatch;
- empty repo/subsystem analysis;
- template-like cases;
- cases based only on force-sync or `.gitattributes` evidence;
- HDF/WiFi/Boot/Product case titles that do not match evidence paths;
- too-short generated runbook/template/checklist files;
- generated outputs contradicting `task_profile.yaml`.

## Logs

Stage logs are written under:

```text
porting_knowledge_output/_codex_stage_logs/
```

Stage JSON results are written under:

```text
porting_knowledge_output/_stage_results/
```

## Recommended Rerun After Updating

If raw records already exist, rerun only the semantic tail:

```bash
bash tools/run_stage.sh "$PWD" 04_semantic_analyzer porting_knowledge_output
bash tools/run_stage.sh "$PWD" 05_case_kb_builder porting_knowledge_output
bash tools/run_stage.sh "$PWD" 06_skill_generator porting_knowledge_output
bash tools/run_stage.sh "$PWD" 07_final_auditor porting_knowledge_output
```
