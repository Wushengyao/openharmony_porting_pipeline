# Local Device Automation

Use this runbook when an OpenHarmony task needs device operations through the
Windows oh-auto service: HDC, serial, flashing, screenshots, smoke checks,
bugreports, or recovery loops.

Keep this file device-neutral. Do not add concrete board IDs, COM ports,
flash templates, WiFi credentials, Windows image paths, or product-specific
workarounds here. Put those values in the oh-auto profile and, when needed, a
device-specific reference such as `docs/musepaper2_local_device_automation.md`.

## Discovery First

Before any device operation, query the automation service:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py health
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py status
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py profile <profile-id>
```

Use profile data instead of hard-coded targets:

- device id;
- USB/TCP/UART connect target;
- serial port and baudrate;
- flash template id;
- allowed Windows image roots;
- recovery command;
- product, vendor, SoC, architecture, and image naming conventions.

If the service is unreachable, treat it as an automation/tunnel problem, not as
evidence that the board is disconnected or the image failed to boot.

## Safety Rules

- Do not use Linux-local HDC, serial ports, or flashers unless the task
  explicitly proves the target is visible on Linux.
- Use `oh_autoctl.py` or the oh-auto HTTP API for device operations.
- Treat every flash, shell, serial, bugreport, push, pull, or long log capture
  as a job. Persist the `job_id`, stdout, stderr, and events in the active
  iteration record.
- Do not resubmit a flash blindly after a timeout. Query the existing job,
  resume logs/events, and classify the state first.
- Inspect stdout for expected payloads. A succeeded job can still contain
  `Offline`, `need connect-key`, `[Empty]`, or no useful output.
- When a shell command contains device-side arguments beginning with `-`, pass
  the whole command after `--` so local argparse does not consume them.
- Before running xDevice OHJSUnit formal evidence, avoid sidecar HDC, serial,
  screenshots, manual UI, or hilog unless the run is explicitly diagnostic.

## Flash Loop

Use the profile's flash template id:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  preflight --template-id <template-id>
```

If the image exists only on Linux, upload it:

```bash
ARTIFACT_ID=$(python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  --timeout-sec 1200 upload /path/to/image.zip --id-only)
```

If the image must also be staged on Windows and the destination is inside an
allowed local root, promote it:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  --timeout-sec 1200 promote-artifact "$ARTIFACT_ID" --dest "<windows-image-path>"
```

Submit and wait:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  flash <template-id> --image "$ARTIFACT_ID"
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  wait <job-id> --events --timeout-sec 1800
```

Save job logs:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py logs <job-id> --stream stdout
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py logs <job-id> --stream stderr
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py logs <job-id> --stream events
```

After flashing, run independent reconnect and smoke checks with the profile's
connect channel and target:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  wait-connected --connect-channel <channel> --connect-target <target> --timeout-sec 240
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  smoke --wait-connected --connect-channel <channel> --connect-target <target>
```

## Recovery

For unattended test loops, a candidate image must prove a recovery route before
long xDevice runs:

- HDC can run the profile's recovery command, commonly `reboot fastboot`; or
- serial console can run the same recovery command; or
- a power/reset controller is configured and tested.

If no automatic recovery route exists, do not start broad destructive,
suspend/resume, boot-slot, or long unattended suites.

## Serial And Logs

Use the profile's serial port and baudrate. Do not copy baudrates from another
device. For boot-failure work, start a bounded serial capture and persist logs
before canceling:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  serial-log --capture-timeout-sec 180 --events
```

Prefer finite HDC snapshots for post-boot logs. Avoid unbounded `dmesg`, long
compound shell snippets, or commands that can leave stale jobs. If a long probe
is required, write detailed output to a device-side file and pull it as an
artifact.

## Device-Specific References

Load a device-specific reference only when the task is about that device.

- MusePaper2 OH6.1 RISC-V:
  `docs/musepaper2_local_device_automation.md` and
  `references/musepaper2_oh61_lessons.md`.
- SBC77:
  `docs/sbc77_local_device_automation.md`.

For a new device, create a concise per-device note only after its profile,
flash template, recovery path, and recurring test quirks are known.
