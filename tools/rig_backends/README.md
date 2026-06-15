# Rig Backends

`tools/rig_controller.py` currently supports:

- `dry-run`: validates command plumbing without touching hardware.
- `command`: maps actions to operator-provided shell commands in a JSON/YAML
  config file.
- `serial-dtr-rts`: uses pyserial to toggle DTR/RTS on a configured serial
  adapter.

Do not mark physical recovery as proven until a configured backend has executed
against the MusePaper2 rig and written its result into the device job ledger.
