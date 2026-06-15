# Version Maintenance

Use version lanes to turn a one-off OpenHarmony migration into a repeatable
upgrade workflow. A lane never proves build, boot, runtime, or release success
by itself; it produces migration evidence and patch-planner inputs.

## Four-tree Inputs

Each lane uses:

- `old_original`: clean old upstream source.
- `old_ported`: old source with board/SoC porting work.
- `new_original`: clean new upstream source.
- `new_workspace`: new source receiving the migration.

## Standard Commands

Classify migration impact:

```bash
python3 tools/version_lane/diff_classifier.py \
  --lane-id oh61-release-to-oh61-lts \
  --old-original /path/to/old_original \
  --old-ported /path/to/old_ported \
  --new-original /path/to/new_original \
  --new-workspace /path/to/new_workspace \
  --out /path/to/lane_out
```

Audit binary debt:

```bash
python3 tools/version_lane/binary_asset_audit.py \
  --stage-result /path/to/stage_result.json \
  --out /path/to/lane_out
```

Create patch-planner tasks:

```bash
python3 tools/version_lane/make_patch_planner_tasks.py \
  --patch-plan /path/to/lane_out/four_tree/upgrade_patch_plan.yaml \
  --workspace /path/to/new_workspace \
  --out-dir /path/to/lane_out/agent_tasks
```

## Outputs

- `lane_diff_classification.yaml`
- `four_tree/upgrade_porting_work_order.yaml`
- `four_tree/upgrade_patch_plan.yaml`
- `four_tree/external_dependency_followup.yaml`
- `lane_binary_asset_audit.yaml`
- `agent_tasks/*/task.yaml`

## Acceptance

A lane is ready for source work when:

- four-tree classification completed without tool failure;
- binary dependencies are listed with provenance or explicit debt;
- manual migration candidates have patch-planner tasks;
- high-risk paths are marked for main-Agent approval;
- build/boot/test gates are still marked unknown until real evidence exists.

## MusePaper2 Rule

For MusePaper2 OH6.x RISC-V, keep the original porting objective visible:
preserve product functions while migrating from the known OH6.0 RISC-V port to
the next OpenHarmony version. Do not delete features to make a lane look clean.
