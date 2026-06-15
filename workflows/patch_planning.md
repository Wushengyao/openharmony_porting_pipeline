# Patch Planning Workflow

1. Start from a requirement record, evidence pack, or triage output.
2. Run `repo-surveyor` if ownership or file boundaries are unclear.
3. Run `runtime-hdf-reviewer` or `build-log-triager` for noisy failures.
4. Run `patch-planner` to produce:
   - `patch_plan.yaml`
   - `risk_assessment.md`
   - `validation_plan.md`
5. Main Agent reviews risk, path whitelist, and expected acceptance gate.
6. Only then create a `patch-writer` task.

Do not skip the planning step for boot, HDF, init, permission, firmware,
binary, partition, or flashing related work.
