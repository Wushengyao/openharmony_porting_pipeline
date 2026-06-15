# Regression Acceptance Workflow

1. Load the current evidence pack and baseline evidence pack.
2. Compare every acceptance gate independently.
3. Mark missing evidence as `unknown` or `not_run`, not passed.
4. Record new failures, disappeared failures, and changed debt severity.
5. Escalate waiver requests to the main Agent.
6. Produce `regression_matrix.yaml` and `risk_items.yaml`.

An RC claim requires evidence for the gates selected by the user. A release
claim requires the release gate.
