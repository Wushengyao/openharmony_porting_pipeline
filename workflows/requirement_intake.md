# Requirement Intake

Use this template before decomposing a new OpenHarmony porting request.

## Required Fields

- goal
- board/product
- OpenHarmony version
- architecture
- source roots or manifests
- target subsystem
- acceptance conditions
- known non-goals
- paths or features that must not be changed
- external dependencies and binary assets
- device availability and recovery path

## Output

Create a requirement record under the project work directory and link it from
the first `agent_task` or evidence pack. Unknowns become explicit questions or
`uncertainty_ledger` items.
