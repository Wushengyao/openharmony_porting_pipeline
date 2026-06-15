# Operation Approval Policy

This policy defines when a subagent or deterministic tool must stop and request
main-Agent approval before continuing.

## Always Requires Approval

- Flashing an image, changing a flash template, or touching partition layout.
- Physical recovery operations: power cycle, USB reconnect, relay control, or
  rig-controller actions.
- Boot chain, bootloader, firmware, signing, kernel module, or closed binary
  replacement.
- HDF startup, init, SELinux, permission policy, or critical service behavior.
- File deletion, generated-tree rewrite, mass formatting, or broad refactors.
- Accepting a waiver, declaring an RC, or declaring release readiness.

## Required Approval Record

Record the approval in the active task or iteration directory before the action:

```yaml
approval_id: APPROVAL-YYYYMMDD-N
approved_by: main_agent
operation: flash_image
scope:
  workspace: /path/to/ohos
  paths:
    - vendor/example/product
evidence_refs:
  - evidence_packs/iteration123/manifest.yaml
risk_items:
  - risk_items.yaml#RISK-001
rollback_plan: docs/recovery_plan.md
budget:
  max_flash_attempts: 1
  max_reboots: 2
expires_after_iteration: iteration123
```

## Stop Conditions

Stop instead of acting when:

- the evidence reference is missing or ambiguous;
- the requested action exceeds the task budget;
- another writer already owns the OpenHarmony workspace;
- a device job is still running or its final state is unknown;
- the diff risk scanner reports high risk without an approval record.
