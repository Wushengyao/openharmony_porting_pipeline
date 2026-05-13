# OpenHarmony Porting Pipeline

Evidence-bound pipeline for extracting reusable OpenHarmony board/SoC porting knowledge from a repo-managed workspace.

## Goal

The pipeline classifies the porting scenario, extracts repo and raw change records, audits dirty workspace and binary assets, computes statistics, builds semantic and case knowledge, generates a reusable Skill, and runs a final audit.

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

## Deterministic Stages

The heavy data stages default to deterministic local generators for repeatability:

- `03_statistics_qc`: `tools/aggregate_stats.py`
- `04_semantic_analyzer`: `tools/generate_semantic_analysis.py`
- `05_case_kb_builder`: `tools/generate_case_kb.py`
- `06_skill_generator`: `tools/generate_skill_output.py`
- `07_final_auditor`: `tools/run_final_audit.py`

Set the corresponding environment variable to `0` to force model execution for a stage:

```bash
DETERMINISTIC_STATISTICS_QC=0 bash tools/run_stage.sh /path/to/ohos 03_statistics_qc
```

## Evidence Rules

- Commit claims cite `repo_path + commit_hash`.
- File claims cite `repo_path + file_path`.
- Binary claims cite `path + sha256`.
- Dirty workspace evidence is separate from committed history.
- Statistics are copied from `02_statistics/statistics_summary.json`.

## Logs

Stage logs are written under:

```text
porting_knowledge_output/_codex_stage_logs/
```

Stage JSON results are written under:

```text
porting_knowledge_output/_stage_results/
```

