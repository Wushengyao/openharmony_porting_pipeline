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
