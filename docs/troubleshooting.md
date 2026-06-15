# Troubleshooting

## oh-auto Connection Refused

Treat `ConnectionRefusedError` as an automation service or tunnel problem, not
as board proof. Run:

```bash
python3 tools/oh_autoctl.py capabilities
python3 tools/oh_autoctl.py status
```

Do not submit flash or HDC jobs until the service is reachable.

## HDC Offline

HDC can be offline during boot or immediately after flashing. Query the job and
wait for the approved reconnect path before resubmitting operations. A job-level
success is not enough; shell or smoke output must be checked for `Offline`,
`No any connected target`, or `ExecuteCommand need connect-key`.

## Serial Noise

OpenHarmony serial logs can contain baseline errors. Use:

```bash
python3 tools/log_slice.py --log serial.log \
  --taxonomy taxonomies/runtime_error_taxonomy.yaml \
  --out-dir serial_slices
python3 tools/panic_classifier.py --log serial.log --out panic_classification.yaml
```

Treat kernel panic, watchdog, bootloop, init/HDF startup, and permission-policy
findings as escalation items.

## Kernel Panic Or Bootloop

Stop unattended flash loops. Preserve the serial excerpt, classify the panic,
and require a recovery plan before continuing. For MusePaper2-style recovery
work, the first milestone is a self-recoverable image that can reach
`reboot fastboot` through HDC or serial.

## xDevice Cannot Find Device

Separate environment readiness from device runtime state:

- xDevice package and Python environment
- HDC binary path and server state
- selected connect key
- report directory permissions
- device online state

Run a small suite or list command before widening to formal suites.

## HATS Flake

Do not widen retries blindly. Record the failing case id, report path, timeout,
device state, and whether rerun scope is a flake check or a real regression
check.

## Binary Or Secret Finding

Run:

```bash
python3 tools/secret_and_binary_scanner.py --repo /path/to/ohos --out scan.yaml
```

Binary assets require hash, usage evidence, and provenance or dependency debt.
Secret findings must be removed or explicitly handled before commit or release
handoff.
