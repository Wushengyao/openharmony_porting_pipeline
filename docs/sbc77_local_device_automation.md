# SBC77 Local Device Automation

Use this device-specific note when operating an SBC77 board for OpenHarmony
image bring-up or XTS failure repair. Keep concrete lab values such as serial
port names, HDC target ids, SD-card device paths, and Windows staging paths in
the oh-auto profile or the active work record.

Source documents:

- `/data1/WSY/filetransfer/OHOS/EsweiXTS/docs/SBC77使用文档.md`
- `/data1/WSY/filetransfer/OHOS/EsweiXTS/docs/SBC77单板的OH镜像打包烧录方法.md`

The first source file is titled `EBC77使用文档`; treat it as the SBC77 board
manual only when the current task context confirms this board identity.

## Contents

- [Known Hardware Facts](#known-hardware-facts)
- [Bootloader Update Flow](#bootloader-update-flow)
- [OpenHarmony WIC Packaging And SD Flash](#openharmony-wic-packaging-and-sd-flash)
- [Automation Boundaries](#automation-boundaries)
- [XTS Repair Loop Notes](#xts-repair-loop-notes)

## Known Hardware Facts

- Power: Type-C must be powered by a charger. Direct PC Type-C power may not
  boot the board.
- Serial: micro USB exposes the console at 115200 baud.
- Display: micro HDMI is the video output.
- Bootloader update media: a USB storage device is inserted into the board's
  USB 2.0 port and operated from U-Boot.
- OpenHarmony runtime image media: write `OpenHarmony.wic` to an SD card, then
  insert the SD card and power on the board.

## Bootloader Update Flow

Treat bootloader burning as a manual or explicitly approved destructive
operation. It changes SPI flash state and can strand the board if interrupted.

Prepare a USB storage device on Linux:

```bash
dmesg
lsblk
fdisk /dev/sdX
mkfs.ext4 /dev/sdX1
mount /dev/sdX1 /media/usb0
cp bootloader-sbc.bin /media/usb0/
umount /dev/sdX1
```

At the U-Boot prompt, after serial is connected and the USB storage device is
inserted into the board USB 2.0 port:

```text
usb reset
ls usb 0
ext4load usb 0 0x90000000 bootloader-sbc.bin
fatload usb 0 0x90000000 bootloader-sbc.bin
es_burn erase flash
es_burn write 0x90000000 flash
env default -a
saveenv
reset
```

Use either `ext4load` or `fatload` according to the prepared filesystem. Before
`es_burn write 0x90000000 flash`, confirm that the load command actually read
`bootloader-sbc.bin` successfully. The source documentation records an invalid
image type failure for the same write command when the image/load state was not
valid, and records `es_burn erase 0x90000000 flash` as an invalid erase form.

For new boards, the source document also records a manual environment erase
step:

```text
env erase
reset
```

If the board reports bootchain download failure after environment erase, the
documented recovery is to connect the USB used for USB boot to the host, reset
into USB boot mode, and copy `bootloader-sbc.bin` into the host-mounted
`ESWIN-2030` mass-storage path. Preserve the complete serial log before and
after this recovery.

## OpenHarmony WIC Packaging And SD Flash

SBC77 OpenHarmony images are packaged as an SD-card image named
`OpenHarmony.wic`.

`genimage` is the packaging tool. It can be built from upstream `genimage`
tag `v18`, or an existing compiled binary can be used if the host glibc version
matches the binary requirement from the source document.

Expected packaging layout:

- Place OpenHarmony image files under an `input/` directory.
- The source example moves `images` to `input` under
  `out/<product>/packages/phone`.
- Run `genimage` with `OpenHarmony_image.cfg`.

```bash
genimage --config OpenHarmony_image.cfg --outputpath . --rootpath .
```

Write the WIC to an SD card. This is destructive; verify `/dev/sdX` through
`dmesg` and `lsblk` immediately before running `dd`.

```bash
sudo dd if=OpenHarmony.wic of=/dev/sdX bs=4M status=progress && sync
```

After writing, insert the SD card into the SBC77 board and power it on.

## Automation Boundaries

Do not assume SBC77 flashing is compatible with the MusePaper2 Titan template.
SBC77 currently needs a distinct oh-auto profile and probably a distinct flash
template for SD-card WIC writing.

Before a fully automated XTS repair loop is allowed, prove and record:

- oh-auto can access the serial console through the host that owns the micro
  USB serial cable.
- oh-auto can power-cycle or reset the board, or an operator is available for
  manual reset.
- The selected SD-card reader is visible to the automation host and can be
  identified deterministically without risking the host disk.
- The WIC package path, allowed staging root, and SD-card target path are
  configured in the oh-auto profile or template.
- The booted OpenHarmony system exposes HDC, including a stable target id or
  a reliable connect procedure.
- A recovery route exists when an image fails to boot: serial U-Boot
  interaction, power/reset controller, known-good SD card swap, or a documented
  manual intervention window.

## XTS Repair Loop Notes

For source-level XTS failure repair, keep the loop:

1. Build changed tests or image on the Linux build server.
2. Package `OpenHarmony.wic` through the product's genimage flow.
3. Flash the SD card through a checked oh-auto SD-card template, or record the
   manual flash as external evidence until that template exists.
4. Boot the board with charger power and capture serial from reset through HDC
   readiness.
5. Run a small xDevice smoke module before widening to full suites.
6. Preserve xDevice reports, serial logs, HDC target selection, image hash, and
   source commits in the active work record.

If the board does not expose HDC after boot, do not start full ACTS/HATS/SSTS
runs. First close boot, service, network, time, and HDC readiness.
