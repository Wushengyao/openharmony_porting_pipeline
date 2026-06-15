# Rig Controller

The rig-controller is the optional physical recovery layer under oh-auto. It is
used only after the main Agent or `device-automation-steward` has a bounded
recovery plan.

## Commands

Dry run:

```bash
python3 tools/rig_controller.py status --backend dry-run
python3 tools/rig_controller.py long-press-power --backend dry-run --out recovery_action.yaml
```

Serial DTR/RTS backend:

```bash
python3 tools/rig_controller.py long-press-power \
  --backend serial-dtr-rts \
  --port COM4 \
  --baudrate 115200 \
  --duration-sec 8 \
  --out recovery_action.yaml
```

Command backend:

```yaml
commands:
  long-press-power: powershell -File F:\rig\long_press_power.ps1
  usb-replug: powershell -File F:\rig\usb_replug.ps1
```

```bash
python3 tools/rig_controller.py usb-replug --backend command --config rig.yaml
```

## Recovery Plan Flow

1. Classify serial/HDC logs:

   ```bash
   python3 tools/panic_classifier.py --log serial.log --out panic_summary.yaml
   ```

2. Generate a recovery plan:

   ```bash
   python3 tools/recovery_plan_builder.py \
     --panic-summary panic_summary.yaml \
     --out recovery_plan.yaml
   ```

3. If and only if physical recovery is approved and configured, execute the
   rig-controller action and append it to the device job ledger.

## Boundary

HDC/serial `reboot fastboot` and boot escape remain the preferred recovery path.
Physical recovery is a last resort for panic, bootloop, or total transport loss.
Never hide a boot or HDF regression by automatically power-cycling in a loop.
