# Stage Contract

Every stage must produce a final JSON message conforming to `schemas/stage_result.schema.json` unless a stage-specific schema is provided.

Required final message fields:

```json
{
  "stage": "04_semantic_analyzer",
  "status": "passed|blocked|partial",
  "summary": "short summary",
  "input_files_read": [],
  "output_files_written": [],
  "blocking_issues": [],
  "non_blocking_issues": [],
  "next_stage_inputs": []
}
```

Stages must not communicate by chat history. They communicate by files only.

Each attempted stage run has an attempt id (`run_id`). Pending results, ndjson logs, and validation logs for a stage must share the same attempt id until validation passes. Only validation-passed attempts may be promoted to `_stage_results/<stage>.json` and copied to canonical `_codex_stage_logs/<stage>.validation.log`. Failed attempts belong under `_codex_stage_logs/_failed_attempts/<stage>/<run_id>/`.
