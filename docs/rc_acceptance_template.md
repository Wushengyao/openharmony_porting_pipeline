# RC Acceptance Template

Use this template for OpenHarmony porting RC candidates. It prevents a build or
smoke pass from being overstated as release readiness.

## Candidate

- Board:
- OS version:
- Architecture:
- Source revision:
- Patch revision:
- Image path:
- Image SHA256:
- Build command:
- Package command:
- Flash job id:

## Gate State

Link `acceptance_state.yaml` that validates against
`schemas/acceptance_state.schema.json`.

Required gates:

- build
- package
- flash
- boot
- HDC
- UI
- subsystem smoke
- HATS native subset
- xDevice formal
- release

Each gate must state one of: `passed`, `failed`, `blocked`, `partial`,
`not_run`, or `unknown`.

## Evidence Index

- Evidence pack:
- Build log summary:
- Package log summary:
- Serial excerpt:
- HDC excerpt:
- Screenshots:
- HATS or xDevice report:
- Diff risk scan:
- Secret and binary scan:

## Known Debts

Record unresolved items with severity, evidence, expected owner, and acceptance
impact. Compile-only stubs, missing binary provenance, unavailable special
hardware, or non-automated recovery must remain visible.

## Wording Rules

- Say "RC candidate" only when build, package, flash, boot, HDC, UI, and the
  intended smoke gates have evidence.
- Say "native HATS subset passed" only for native subset evidence.
- Say "formal xDevice passed" only for a matching xDevice report.
- Say "release accepted" only when the release gate is explicitly approved.
