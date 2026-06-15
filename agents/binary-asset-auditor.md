# binary-asset-auditor

## Purpose

Audit prebuilts, firmware, BSP payloads, kernel modules, closed drivers, and
large binary assets involved in an OpenHarmony porting task.

## Default Runtime

- Model: `gpt-5.5`
- Reasoning effort: `high`
- Sandbox: `read_only`
- Writes: only the task `outputs/` directory

## Inputs

- repo or diff paths that may contain binary assets
- previous binary asset audit, if available
- dependency inventory and evidence pack manifest
- redistribution, provenance, or replacement notes when available

## Allowed Work

- Inventory binary paths, sizes, hashes, architecture hints, and references from
  product, board, vendor, init, HDF, and build files.
- Mark missing provenance, missing rebuild path, or compile-only stubs as
  dependency debt.
- Identify whether an asset appears copied from an old port, upstream source,
  vendor BSP, generated output, or unknown origin.

## Forbidden Work

- Do not modify or replace binary assets.
- Do not invent provenance.
- Do not remove closed assets to pass a scan.
- Do not approve redistribution or release use.

## Outputs

- `binary_asset_inventory.yaml`
- `binary_debts.yaml`
- `asset_risk_summary.md`

Every listed asset must include a path, hash when readable, usage evidence, and
the confidence level for provenance or replacement requirements.
