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
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py preflight
```

## Mandatory Rules

- Do not assume HDC, serial ports, Titan flasher, or Windows paths exist on the Linux server.
- Do not run local Linux shell commands to flash or control the OpenHarmony device.
- Use only the OpenHarmony automation HTTP API or `tools/oh_autoctl.py`.
- Always run discovery before device operations: `oh_autoctl.py capabilities`.
- Always run preflight before flashing: `oh_autoctl.py preflight --template-id musepaper2-titan`.
- Treat all device operations as jobs. Persist every returned `job_id` in the build log before waiting.
- If a POST request times out after a `job_id` was returned, never resubmit the same flash blindly. Query the existing `job_id`.
- If the network drops, first query `oh_autoctl.py job JOB_ID`, then resume logs/events.
- HDC `Offline` shortly after flashing is normal. Wait for job completion instead of treating it as immediate failure.
- Only use `template_id=musepaper2-titan` for MusePaper2 Titan flashing unless `/capabilities` says another valid template should be used.

## Standard Workflow

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

Continue only if `ok=true`.

3. Upload image artifact if the image is on the Linux server:

```bash
ARTIFACT_ID=$(python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py upload /path/to/openharmony-spacemit-k1-musepaper2.zip --id-only)
```

If the image already exists on the Windows host and is inside `allowed_local_roots`, pass that Windows path as `--image` instead.

MusePaper2 porting convention:

- Known-good OH6.0 control package:
  `F:\images\PortingTest\6.0\openharmony-spacemit-k1-musepaper2.zip`
- Fresh OH6.1 test packages after each successful build:
  `F:\images\PortingTest\6.1\openharmony-spacemit-k1-musepaper2.zip`

Before using a direct `F:\...` path, confirm `oh_autoctl.py capabilities`
shows `F:\images\PortingTest` or the exact staging directory in
`allowed_local_roots`. If it does not, use `oh_autoctl.py upload` from the Linux
build host and flash the returned artifact id. A direct `F:\...` path outside
`allowed_local_roots` fails before flashing and does not modify the device.

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
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py smoke
```

## Serial Console

MusePaper2 的本机串口控制台当前配置为 `COM4`、`115200`。Agent 可以通过自动化服务发送串口命令，不要直接在 Linux 服务器上假设存在该串口。

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "echo oh_auto_serial_probe" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "uname -a" --wait
```

串口响应包含命令回显和 `#` 提示符；判断业务输出时要避开这些回显/提示符噪声。

MusePaper2 可以通过 HDC 或串口控制台执行 `reboot fastboot` 进入 Titan
烧录模式。OpenHarmony 已启动且 HDC 可用时优先用 HDC；HDC 不可用但串口
控制台仍响应时使用串口：

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell "reboot fastboot" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py serial "reboot fastboot" --wait
```

## Failure Handling

- `agent_unreachable`: automation service cannot be reached. Check tunnel, VPN, or Windows service.
- `auth_failed`: API key is enabled on the service and the provided key is missing or invalid.
- `device_busy`: another job is running. Query status and wait or attach to known `job_id`.
- `device_offline`: HDC is not connected before flash. Do not modify code for this; recover the device connection first.
- `artifact_error`: upload failed, checksum/path problem, or Windows path not whitelisted.
- `flash_failed`: collect stdout/stderr/events from the job, then decide retry or human intervention.
- `smoke_failed`: flash completed but OpenHarmony validation failed. Use logs/system info to decide next code modification.

## Useful Commands

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py status
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell echo oh_auto_agent_probe --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell "param get const.product.name" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py shell "param get const.ohos.fullname" --wait
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py job "$JOB_ID"
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py cancel "$JOB_ID"
```
