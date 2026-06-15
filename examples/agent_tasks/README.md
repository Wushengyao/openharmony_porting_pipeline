# Agent Task Examples

These examples show the v0.1 task contract used by the Codex subagent
architecture. Copy one directory under a real `agent_tasks/<task_id>/` root,
replace paths with real evidence paths, then validate the task shape against
`schemas/agent_task.schema.json`.

The examples are intentionally read-heavy. A main Agent should start with these
patterns before introducing writer tasks.

Before dispatching the examples on a real iteration, create a compact evidence
pack and log slices:

```bash
python3 tools/evidence_pack_builder.py --help
python3 tools/log_slice.py --help
```

Writer examples are intentionally absent in v0.2. Create writer tasks only from
an approved `patch-planner` output, a writer-lock record, and a path whitelist.
