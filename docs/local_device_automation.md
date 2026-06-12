# OpenHarmony Porting Skill Addendum: Local Device Automation

将本片段加入服务器端 Linux Codex Agent 的 OpenHarmony 移植技能中。该 Agent 进行“代码修改 -> 编译 -> 刷机 -> 设备验证 -> 下一轮修改”闭环时，必须通过 Windows 本机 OpenHarmony 自动化服务操作开发板。

## Required Environment

Agent 运行前必须获得：

```bash
export OH_AUTO_BASE_URL=http://127.0.0.1:8787/api/v1
export OH_AUTO_DEVICE_ID=default
```

如果通过反向 SSH 隧道访问，`OH_AUTO_BASE_URL` 通常仍是 `http://127.0.0.1:8787/api/v1`。如果通过 VPN 访问，使用 Windows 本机在 VPN 内的地址。
默认不需要 `OH_AUTO_API_KEY`；只有本机服务在配置中启用了 API key 时才设置它。

推荐使用技能内 CLI：

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py health
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py profile musepaper2
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py preflight
```

### Service reachability troubleshooting

If `oh_autoctl.py status`, `health`, or `capabilities` returns
`ConnectionRefusedError: [Errno 111] Connection refused`, treat it as an
automation service or port-forwarding problem. Do not infer that the MusePaper2
board is disconnected or that the image failed to boot.

Record the failure in the active iteration directory and check:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py status 2>&1
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities 2>&1
ss -ltnp | rg ':8787|oh_auto|python' || true
```

If no local listener exists on `127.0.0.1:8787`, the Windows oh-auto service or
the SSH/VPN path to it must be restored before flashing, HDC, or serial
validation can proceed. It is acceptable to add a bounded wait helper that polls
for service recovery and then runs the normal flash/smoke workflow, but do not
leave an unbounded background flash job running.

### Trusted Windows Service Maintenance

The Windows oh-auto service may expose trusted admin operations to this 184-side
Agent. Discover them before attempting service edits:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py admin-status
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
```

If `admin-status.enabled=true`, the Agent may use:

- `admin-shell "COMMAND"` for Windows PowerShell commands in the oh-auto repo root.
- `admin-read-file PATH --out LOCAL_FILE` and `admin-write-file PATH --from-file LOCAL_FILE`.
- `admin-run-check py_compile` for quick syntax checks.
- `admin-run-check pytest` before behavior-sensitive changes.
- `admin-restart` after code/config changes that require a service reload.

Focus edits on these paths unless the current task clearly points elsewhere:

- `src/oh_auto/api.py`, `src/oh_auto/models.py`, `src/oh_auto/admin.py`
- `src/oh_auto/flash.py`, `src/oh_auto/serial_client.py`, `src/oh_auto/storage.py`
- `scripts/oh_autoctl.py`
- `config/oh-auto.yaml` for local runtime config
- `config/flash-templates/*.yaml` for board flashing workflows
- `scripts/start_oh_auto.ps1`, `scripts/restart_oh_auto.ps1`, tunnel/watchdog scripts

After a self-maintenance change, run at least:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py admin-run-check py_compile --command-timeout-sec 60
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py admin-restart --delay-sec 1
sleep 8
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py version
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py profile musepaper2
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py preflight --template-id musepaper2-titan
```

Use admin shell for trusted maintenance only. Do not run broad destructive
cleanup commands unless the exact target path is verified and inside the oh-auto
workspace or configured runtime data directory.

If job events or logs contain `OperationalError: database or disk is full`, do
not treat the board, HDC, or Titan flashing as the root cause. Stop submitting
device jobs and inspect the service state without creating more device work:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py status
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py diagnose-jobs
```

The current Windows service stores new runtime data under `F:\oh-auto-data`
and allows direct image references under `F:\images`. The previous C-drive
accumulation under the repo-local `data\artifacts` and `data\runs` directories
has been cleaned and should not be used for new artifacts. Successful
`musepaper2-titan` jobs include `cleanup_path` and delete the extracted image
directory after smoke checks.
Failed jobs may intentionally retain extracted images under
`F:\oh-auto-data\runs\<job_id>` for debugging. If disk pressure recurs, clean
old generated artifacts/runs under the runtime `data_dir` reported by
`/capabilities`, restart the service, then require `status` to show no stale
`running_jobs` and `preflight --template-id musepaper2-titan` to return
`ok=true` before continuing.

## Mandatory Rules

- Do not assume HDC, serial ports, Titan flasher, or Windows paths exist on the Linux server.
- Do not run local Linux shell commands to flash or control the OpenHarmony device.
- Use only the OpenHarmony automation HTTP API or `tools/oh_autoctl.py`.
- Always run discovery before device operations: `oh_autoctl.py capabilities`.
- Always run preflight before flashing: `oh_autoctl.py preflight --template-id musepaper2-titan`.
- Interpret preflight as flash-job submission readiness, not proof of Titan burn
  mode. On service version `0.2.0+`, use `oh_autoctl.py wait-titan-fastboot`
  after `reboot fastboot` when the loop needs explicit Titan burn-mode evidence.
- Treat all device operations as jobs. Persist every returned `job_id` in the build log before waiting.
- If a POST request times out after a `job_id` was returned, never resubmit the same flash blindly. Query the existing `job_id`.
- If the network drops, first query `oh_autoctl.py job JOB_ID`, then resume logs/events.
- HDC `Offline` shortly after flashing is normal. Wait for job completion instead of treating it as immediate failure.
- Only use `template_id=musepaper2-titan` for MusePaper2 Titan flashing unless `/capabilities` says another valid template should be used.

## Standard Workflow

### MusePaper2 recovery-first gate

For the ongoing MusePaper2 OH6.1 port, the first boot milestone is not a full
UI session. The first milestone is:

- the kernel and init do not reach a panic path during early boot;
- HDC or the serial console becomes responsive long enough to run
  `reboot fastboot`;
- the next flash cycle can be entered without a manual board reset.

If a build reaches this milestone but later user-space services fail, preserve
the milestone and continue diagnosis from a self-recoverable image. Do not
weaken critical service policy or remove product functions just to hide a
panic. Prefer targeted product parameters or narrow runtime workarounds that
keep automatic recovery possible while the underlying service crash is being
investigated.

1. Discover service:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
```

Confirm:

- `service.api_prefix == "/api/v1"`
- `devices` contains `default`
- `flash_templates` contains `musepaper2-titan` with `valid=true`
- `flash_step_types` contains `extract_zip`, `wait_titan_fastboot`, and `titan_flash`

2. Preflight:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py preflight --template-id musepaper2-titan
```

Continue with flash submission only if `ok=true`. If `device_connected=false`
but `template_can_wait_titan_fastboot=true`, the board may already be in Titan
burn mode; HDC Offline alone does not disprove burn mode. The first definitive
burn-mode proof is the flash event `titan_fastboot_found`.

3. Upload image artifact if the image is on the Linux server:

```bash
ARTIFACT_ID=$(python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py upload /path/to/openharmony-spacemit-k1-musepaper2.zip --id-only)
```

For large MusePaper2 zip packages, pass a longer global client timeout before
the `upload` subcommand. The default HTTP timeout may expire before a 700MB+
artifact finishes transferring even though the service is healthy:

```bash
ARTIFACT_ID=$(python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py \
  --timeout-sec 900 upload /path/to/openharmony-spacemit-k1-musepaper2.zip --id-only)
```

If the image already exists on the Windows host under `F:\images` and is inside
`allowed_local_roots`, prefer passing that Windows path as `--image` instead of
uploading it from Linux. This avoids duplicate artifact copies. On service
`0.2.0+`, when the image exists only on Linux but the loop or test team requires
the canonical Windows path, upload once and promote the artifact:

```bash
ARTIFACT_ID=$(python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py upload /path/to/openharmony-spacemit-k1-musepaper2.zip --id-only)
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py promote-artifact "$ARTIFACT_ID" --dest "F:\images\PortingTest\6.1\openharmony-spacemit-k1-musepaper2.zip"
```

The promote operation is Windows-side, uses a temporary file plus atomic replace,
returns `dest_path`, `size`, `sha256`, and `mtime`, and rejects destinations
outside `allowed_local_roots`.

MusePaper2 porting convention:

- Known-good OH6.0 control package:
  `F:\images\PortingTest\6.0\openharmony-spacemit-k1-musepaper2.zip`
- Fresh OH6.1 test packages after each successful build:
  `F:\images\PortingTest\6.1\openharmony-spacemit-k1-musepaper2.zip`

On service `0.3.0+`, prefer querying the rig profile before flash/smoke loops:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py profile musepaper2
```

The profile is the service-side source of truth for the MusePaper2 Titan
template, USB HDC target, UART port and baudrates, staging image paths, and the
current `rc0` artifact/hash.

Before using a direct `F:\...` path, confirm `oh_autoctl.py capabilities`
shows `F:\images` or the exact staging directory in `allowed_local_roots`. If
it does not, use `oh_autoctl.py upload` from the Linux build host and flash the
returned artifact id. A direct `F:\...` path outside `allowed_local_roots`
fails before flashing and does not modify the device.

Storage policy:

- Prefer a direct Windows path for known images under `F:\images\PortingTest\...`.
- Upload only when the image exists only on the Linux build host.
- Do not store new artifacts or run outputs on C drive.
- Current runtime data is under `F:\oh-auto-data`; old small metadata backups,
  if needed, are under `F:\oh-auto-data\legacy-metadata`.
- Successful `musepaper2-titan` flash jobs auto-delete the extracted image
  directory via `cleanup_path`; failed jobs may keep extracted data under
  `F:\oh-auto-data\runs\<job_id>` for debugging.
- Use `oh_autoctl.py download-artifact ARTIFACT_ID --out /linux/path` for pulled
  screenshots, bugreports, and logs. It streams artifact bytes from Windows and
  verifies `X-Artifact-Sha256`; avoid base64 HDC shell workarounds.

4. Submit flash job:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py flash musepaper2-titan --image "$ARTIFACT_ID"
```

Record the returned `job_id`.

5. Wait and stream events:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py wait "$JOB_ID" --events --timeout-sec 1800
```

6. Collect logs:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py logs "$JOB_ID" --stream stdout
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py logs "$JOB_ID" --stream stderr
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py logs "$JOB_ID" --stream events
```

7. Run post-flash smoke checks:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py wait-connected --connect-channel usb --connect-target 0123456789ABCDEF --timeout-sec 240
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py smoke --wait-connected --connect-channel usb --connect-target 0123456789ABCDEF
```

When HDC lists both USB and UART targets, select the concrete USB connect key
before shell/smoke operations, or pass the connect options inline:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py connect --connect-channel usb --connect-target 0123456789ABCDEF
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell --connect-channel usb --connect-target 0123456789ABCDEF "echo oh_auto_agent_probe" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py smoke --wait-connected --connect-channel usb --connect-target 0123456789ABCDEF --set-boot-escape-ack
```

When a device command contains arguments beginning with `-`, pass the whole
device-side command as a single positional string after `--`. Otherwise local
`argparse` may treat options such as `-l`, `-n`, `-s`, or `-a` as
`oh_autoctl.py` options:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell \
  --wait --connect-channel usb --connect-target 0123456789ABCDEF \
  -- "hidumper -s BluetoothHost -a -br"
```

Do not accept a shell job as successful until stdout has been inspected for the
expected payload and does not contain `[Fail]`, `ExecuteCommand need
connect-key`, `Offline`, or `No any connected target`.
Do not accept template `wait_hdc` or template smoke as proof of boot when its
event payload contains `[Empty]`; rerun `wait-connected` and strict smoke from
this CLI.

### Post-Boot HDC Log Snapshots

For finite post-boot hilog checks on the current MusePaper2 rig, prefer a
single HDC shell command such as:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell "hilog -z 80" --wait
```

Important command-shape notes from OH6.1 MusePaper2 validation:

- `hilog -T` filters by tag; it is not a time-window option.
- `hilog -x` cannot be combined with `-z`; `hilog -z N` is the reliable finite
  tail form observed on the device.
- Long `hilog -e` regular expressions fail above 127 characters, and some
  filtered hilog invocations can leave an automation job running even after
  partial stdout appears.
- HDC shell commands containing pipes or compound shell syntax may return
  `Mutlti commands can't be used in combination [CODE: -31]`. Prefer a single
  device command, or collect a finite `hilog -z N` snapshot and filter it on the
  build host.
- Avoid unbounded or unknown HDC shell probes during automation, especially
  bare `dmesg` and `which <possibly-missing-command>`. On the MusePaper2 OH6.1
  rig these have produced stale service-side `hdc_shell` jobs that do not stop
  promptly after `cancel`. Use known-good finite commands, explicit command
  timeouts, or a screenshot/base64 path that has already been validated.
- When a device-side shell snippet really needs variables such as `$f`, quote
  the whole command so the Linux build-host shell cannot expand them before
  `oh_autoctl.py` submits the job. A lost variable can turn `cat "$f"` into
  `cat` with no arguments, leaving a stale `hdc_shell` job that holds the
  device lock; recover with `oh_autoctl.py status` followed by targeted
  `oh_autoctl.py cancel JOB_ID`.
- After any long or experimental log capture, run `oh_autoctl.py status` and
  cancel stale running jobs before flashing or submitting another device job.

For screenshots, `snapshot_display -f /data/local/tmp/name.jpeg` proves the
display pipeline can capture a frame and `pull` saves it as a Windows-side
artifact. On service `0.2.0+`, download the artifact content directly:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py download-artifact ARTIFACT_ID --out /path/to/records/screenshot.jpeg
```

The CLI streams bytes from Windows and verifies the returned sha256 header.

For full-device evidence after boot, use the service-side bugreport operation
instead of hand-rolling a large set of HDC pulls:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py bugreport --filename musepaper2-bugreport.zip --wait --connect-channel usb --connect-target 0123456789ABCDEF
```

Save the returned `job_id` and logs in the active iteration directory. A
bugreport can be slow; set `--command-timeout-sec` and `--timeout-sec` together
when collecting it during unattended loops.

## Serial Console

MusePaper2 的本机串口控制台当前配置为 `COM4`、`115200`。Agent 可以通过自动化服务发送串口命令，不要直接在 Linux 服务器上假设存在该串口。

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "echo oh_auto_serial_probe" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "uname -a" --wait
```

串口响应包含命令回显和 `#` 提示符；判断业务输出时要避开这些回显/提示符噪声。
MusePaper2 的串口命令和 `serial-log` 启动日志优先使用
`--port COM4 --baudrate 115200`。不要把 HDC 连接参数里的 `921600` 直接套
到串口日志上，除非现场重新探测确认；该波特率可能只产生乱码，而 `115200`
可以得到可交互 console。

MusePaper2 可以通过 HDC 或串口控制台执行 `reboot fastboot` 进入 Titan
烧录模式。OpenHarmony 已启动且 HDC 可用时优先用 HDC；HDC 不可用但串口
控制台仍响应时使用串口：

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell "reboot fastboot" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "reboot fastboot" --wait
```

During boot-failure iterations, start serial capture before or immediately after
flashing and persist the job id plus stdout/events into the iteration log. Use
long enough read/idle windows to keep the last seconds before a panic; avoid
canceling a serial job until its logs have been saved. If the service does not
offer a continuous bootlog API, treat that as an automation gap and request a
service-side serial-capture endpoint instead of relying on short command
transactions.

Start continuous serial capture with:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial-log --capture-timeout-sec 180 --events
```

Persist the returned `job_id`, then save logs:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py logs "$SERIAL_JOB_ID" --stream stdout
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py logs "$SERIAL_JOB_ID" --stream events
```

Use `oh_autoctl.py cancel "$SERIAL_JOB_ID"` only after stdout/events have been
saved, or when the capture job is clearly blocking the next serial operation.
For post-HDC log capture, use finite HDC shell snapshots first. The
service-side `oh_autoctl.py hilog` subcommand is useful when the service can
bound the capture, but long-running invocations may time out as failed jobs on
older service versions; always inspect `oh_autoctl.py status` afterward.

For a MusePaper2 image that already panic-stopped, HDC and serial command jobs
may both report no usable shell even when the automation job itself is marked
successful. Inspect stdout for strings such as `need connect-key`, missing
prompts, or empty command output before assuming the device can recover itself.

## Boot Escape Policy

Use the boot escape watchdog differently across phases.

For unstable images that may panic before HDC or serial command access, keep the
strict debug profile:

```text
startup.porting.boot_escape.timeout_sec=60
startup.porting.boot_escape.accept_boot_completed=false
startup.porting.boot_escape.ack=false
```

Only set `startup.porting.boot_escape.ack=true` after HDC or serial command
access has been verified. This prevents a board from remaining stuck in a
pre-HDC failure state when no one is near the device.

For an `rc0` or test-team candidate that already reaches boot completed, relax
the profile:

```text
startup.porting.boot_escape.timeout_sec=120
startup.porting.boot_escape.accept_boot_completed=true
startup.porting.boot_escape.ack=false
```

This prevents a healthy boot-completed system from unexpectedly returning to
fastboot just because the test team did not run the automation ack command,
while still preserving an escape route if boot completed is never reached.
Automation smoke may still set `startup.porting.boot_escape.ack=true` after
strict HDC validation.

## Failure Handling

- `agent_unreachable`: automation service cannot be reached. Check tunnel, VPN, or Windows service.
- `auth_failed`: API key is enabled on the service and the provided key is missing or invalid.
- `device_busy`: another job is running. Query status and wait or attach to known `job_id`.
- `device_offline`: HDC is not connected before flash. Do not modify code for this; recover the device connection first.
- `artifact_error`: upload failed, checksum/path problem, or Windows path not whitelisted.
- `flash_failed`: collect stdout/stderr/events from the job, then decide retry or human intervention.
- `smoke_failed`: flash completed but OpenHarmony validation failed. Use logs/system info to decide next code modification.

## Human Reset Notification

Until the test rig has power/reset control, a MusePaper2 kernel panic can block
the automatic loop because the board cannot execute `reboot fastboot`. When this
happens, immediately persist the reason, image hash, relevant serial excerpt,
and last flash/log job ids, then notify the operator that a manual reset is
needed.

The Linux build host may not have a local MTA. If `mail`, `sendmail`, `msmtp`,
or another configured notifier is unavailable, do not invent an email path.
Use the conversation plus iteration log as the fallback. If a webhook/SMTP
endpoint is supplied later, send the same reset-needed summary through that
configured endpoint, for example via `curl`.

## Useful Commands

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py status
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell echo oh_auto_agent_probe --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell "param get const.product.name" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell "param get const.ohos.fullname" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py job "$JOB_ID"
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py cancel "$JOB_ID"
```
