# Build, Flash, Test Workflow

Recommended order:

1. Build through the product `build.sh` entrypoint.
2. Package image through the product packaging script.
3. Record image size, SHA256, and command lines.
4. Run oh-auto discovery and preflight.
5. Flash through oh-auto and preserve `job_id`.
6. Wait for boot or recovery-first milestone.
7. Collect HDC, serial, screenshots, and smoke results.
8. Run low-cost HATS/native smoke before widening.
9. Run formal xDevice suites only with matching resources and explicit scope.
10. Build an evidence pack and update acceptance state.

Never treat build pass as boot pass. Never treat native HATS subset pass as
formal xDevice pass.
