# Stage 00: Scope Classifier

Use skill: `openharmony_porting_00_scope_classifier`.


This is a fresh isolated Codex session.
Do not assume previous chat context.
Do not resume or rely on prior conversations.
Read only the input files listed in this prompt, plus source files only when the stage explicitly requires shell/git inspection.
Do not read archived failed runs or previous final reports unless explicitly listed.
Write only the required output files.
At the end, return a JSON object conforming to the provided output schema.


## Inputs allowed

- Current workspace directory tree
- repo manifest if available
- user-provided notes under `porting_knowledge_input/` if present
- existing `00_config/task_config.yaml` only if present

## Required actions

1. Create `porting_knowledge_output/00_config/`.
2. Inspect minimal evidence: manifest, product/vendor/device paths, SoC/board names, obvious kernel/toolchain paths.
3. Write `porting_knowledge_output/00_config/task_profile.yaml`.
4. Write `porting_knowledge_output/00_config/scope_classification_report.md`.

## Classification rule

For T113/T113-S3/T113-i: if evidence indicates ARM runs OpenHarmony and RISC-V is auxiliary/firmware/coproc, set:

```yaml
scenario_type:
  - board_soc_arm_primary
  - heterogeneous_aux_core
openharmony_runtime_core: arm
riscv_role: auxiliary_core
treat_riscv_as_primary_arch: false
```

For RuyiOS/Spacemit-like riscv64 distribution projects, classify as `riscv_primary_distribution`.

## Final JSON

Return `stage_result` JSON only in the final answer.
