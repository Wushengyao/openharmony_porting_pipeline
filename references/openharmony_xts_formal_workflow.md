# OpenHarmony Formal XTS And xDevice Workflow

Use this reference when a porting task moves from native smoke tests into
formal XTS/xDevice execution, when official XTS resources must be fetched, or
when a Windows workbench is the only host that can see the target through HDC.

## Official Inputs

- Treat `https://www.openharmony.cn/systematic?tab=xts` as the user-facing
  entry. The SPA loads the machine-readable document from
  `https://compatibility.openharmony.cn/certificate/external/document/xts`.
- Also fetch the compatibility guide from
  `https://compatibility.openharmony.cn/certificate/external/document/guid`
  when documenting the full certification flow.
- Persist the raw JSON and a Markdown extraction in the iteration record before
  downloading suites or resources. The page can change independently of the
  source tree.

## Version, Architecture, And Resource Rules

- Match image version, suite version, resource package, and system type. Do not
  use an older official suite or resource as formal evidence for a newer target
  release unless the official page explicitly says it is shared.
- Official standard-system executable suites may be published only for a common
  architecture such as arm32. For RISC-V64, arm64, x86, small-system, or
  otherwise missing targets, build the suites from the matching OpenHarmony
  release source instead of running the wrong prebuilt.
- If the target release is not listed on the official XTS download page, record
  the gap and use same-release source-built suites for engineering validation.
  Do not silently mix the newest listed resource set into the target release.
- Download resource packages only when the official page has an exact matching
  release and system type. Place them under `<suite>/resource` or pass
  `-respath <resource-dir>`.
- Some signed OBS URLs are signed for GET; `curl -I` can fail with
  `SignatureDoesNotMatch`. Use the official page/API as the source of truth and
  prefer an actual controlled download when the version match is valid.

## Suite Build And Layout

- For a standard-system product, the formal suite set is normally ACTS,
  ACTS-Validator, HATS, DCTS, and SSTS. DCTS may need a distributed test box or
  two-device network setup.
- Build target-architecture suites from the target workspace, for example:

```bash
cd test/xts/hats
./build.sh product_name=<product> system_size=standard
```

- On hosts where `/usr/bin/python3` is older than Python 3.10, run XTS build
  wrappers with the OpenHarmony prebuilt Python first in `PATH`; the OH6.1 XTS
  CI helpers use syntax such as `str | None`:

```bash
PATH="$PWD/prebuilts/python/linux-x86/3.11.4/bin:$PATH" \
  ./test/xts/acts/build.sh product_name=musepaper2 system_size=standard \
  target_arch=riscv64 xts_suitetype=bin,hap_dynamic
```

- For MusePaper2 OH6.1 RISC-V ACTS, if GN fails at
  `test/xts/acts/commonlibrary/toolchain/BUILD.gn` with `rebase_path("")`,
  compare the already-ported OH6.0 RISC-V tree. The expected fix is to add a
  `target_cpu == "riscv64"` branch to `tar_dllib`, mirroring arm64/x86_64 and
  generating `libc-test-lib.tar`; do not drop the commonlibrary/toolchain ACTS
  coverage.
- If Ninja then reports a missing SDK library under
  `prebuilts/ohos-sdk/linux/<api>/native/sysroot/usr/lib//`, inspect
  `build/ohos_var.gni`. OH6.1 original may lack the RISC-V branch for
  `target_platform_triple`; add `target_platform_triple =
  "riscv64-linux-ohos"` for `target_cpu == "riscv64"` so ACTS NDK tests use the
  existing architecture-specific SDK libraries instead of flattening them into
  `usr/lib`.
- Generated suite roots are typically under `out/<product>/suites/<suite>` and
  contain `run.bat`, `run.sh`, `config/user_config.xml`, `testcases/`, and
  `tools/xdevice*.tar.gz`.
- For MusePaper2 OH6.1 RISC-V, `out/musepaper2/suites/hats` was sufficient to
  run a formal xDevice HATS probe. At the time of the first probe, ACTS and
  DCTS suite roots had not yet been generated in `out/musepaper2/suites`.

## MusePaper2 Windows Workbench Execution

- The official workflow assumes a Windows workbench connected to the standard
  system device by USB. For the MusePaper2 rig, Windows oh-auto sees HDC target
  `0123456789ABCDEF`; Linux-local `hdc` may not see the target.
- Query oh-auto before a formal run:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py capabilities
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py status
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_autoctl.py admin-status
```

- If oh-auto has admin support, stage the suite zip to a Windows allowed root
  such as `F:\images\PortingTest\6.1`, expand it, and run xDevice from the
  Windows side. Prefer `tools/oh_xts_xdevice_runner.py` for repeatable staging,
  xDevice install, execution, report listing, and summary parsing; use raw
  `admin-shell` only for trusted lab maintenance.
- Use the Python interpreter reported by oh-auto capabilities/admin status, not
  the Windows Store `python` shim. Confirm `hdc` resolves to the workbench HDC:

```powershell
Get-Command hdc
& 'D:\ohos_toolchains\hdc.exe' list targets
```

The MusePaper2 workbench was validated with oh-auto `0.3.0`, Windows Python
`C:\Users\sheng\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`,
HDC `D:\ohos_toolchains\hdc.exe`, and target `0123456789ABCDEF`.

## Minimal Formal Probe

Start with one harmless module before a broad suite:

```bash
python3 /home/ve/.codex/skills/openharmony_porting_pipeline/tools/oh_xts_xdevice_runner.py \
  --suite-dir /path/to/ohos/out/musepaper2/suites/hats \
  --out /path/to/work/records/iterationNNN/runner_hats_getcwd \
  --run-id iterationNNN_hats_getcwd \
  --module HatsGetcwdTest \
  --command-timeout-sec 600 \
  --upload-timeout-sec 1200
```

The runner writes `xts_xdevice_manifest.json`, staged zip upload/promote
evidence, `xdevice_run.json`, `xdevice_summary.json`, and
`report_file_list.json`. Its default report path includes `run_id` so repeated
probes do not reuse a non-empty xDevice report directory.

Manual equivalent:

```powershell
Set-Location 'F:\images\PortingTest\6.1\hats_suite_probe\hats'
& 'C:\Users\sheng\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  -m pip install --user .\tools\xdevice-0.0.0.tar.gz `
  .\tools\xdevice_devicetest-0.0.0.tar.gz `
  .\tools\xdevice_ohos-0.0.0.tar.gz
& 'C:\Users\sheng\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
  -m xdevice run -l HatsGetcwdTest -sn 0123456789ABCDEF `
  -c .\config\user_config.xml -tcpath .\testcases -rp .\reports_probe_getcwd
```

Important details:

- `-c` must point to `config/user_config.xml`, not the `config` directory.
- `-rp .\name` is placed under the suite `reports` directory; for the example
  above the effective path is `hats\reports\reports_probe_getcwd`.
- xDevice can run `remount`, start hilog capture, push tests into
  `/data/local/tmp`, and leave XML outputs on device. Record or clean leftovers
  deliberately.
- Do not start with broad audio, suspend, USB-role, network-topology, active
  slot, or distributed suites. Use clean boots and per-module reboot isolation
  for stateful modules.

## Evidence To Preserve

For each formal XTS/xDevice run, keep:

- official XTS and guide JSON/Markdown snapshots;
- exact suite source workspace, product name, build command, suite root, and
  suite zip hash;
- official resource manifest and downloaded resource hashes, or a recorded
  reason that no matching resource exists;
- oh-auto capabilities/status/profile before and after the run;
- xDevice install/help output when bootstrapping a workbench;
- xDevice command line, stdout/stderr, report directory, `summary.ini`,
  `summary_report.xml`, module result XMLs, and report zip hash;
- device version and architecture evidence such as `uname -m` and
  `param get const.product.software.version`.

The MusePaper2 first formal probe on 2026-06-15 used OH
`OpenHarmony 6.1.0.31`, architecture `riscv64`, and passed
`HatsGetcwdTest` with `tests=1`, `passed=1`, `failed=0`.
