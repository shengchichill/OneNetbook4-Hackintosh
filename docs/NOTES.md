# Technical notes

Root causes and fixes found while bringing up macOS Tahoe on the OneNetbook 4. Each item says what was observed,
why it happened and what the EFI does about it. Values are from this unit (BIOS AMI 5.19, 2021-07-15).

## Boot

- **CPUID**: spoof Ice Lake `0x706E5` (`Cpuid1Data E5060700…`, mask `FFFFFFFF…`) with `MacBookPro16,2`.
  The Comet Lake value copied from an Alder Lake config stops at `EXITBS:START`.
- **MmioWhitelist**: with `DevirtualiseMmio`, PCIe ECAM (`0xC0000000`, 256 MB) and the firmware flash (`0xFF000000`, 16 MB)
  must stay mapped, otherwise boot stops at `EXITBS:START`.
- **CFG Lock** is on (`MSR 0xE2 = 0x74008008`, bit 15) → `AppleXcpmCfgLock`.
- **Slow boot**: OpenCore INFO messages scrolling on the 2560×1600 GOP took ~7 minutes. `DisplayLevel 0x80000002` (errors only) and
  `Target 0` on the daily build; the debug build writes INFO to a file instead (`Target 0x41`).
- **Picker keyboard**: with `KeySupport=false` the builtin picker has no key source at all. `KeySupport=true` works but the firmware
  sends one invalid key at start, which cancels the timeout; `KeyFiltering=true` drops it.
- **BootOrder**: through OpenCore, `efibootmgr` in Linux sees the `RequestBootVarRouting` copy of BootOrder, not the real one.
  The AMI firmware also deletes boot entries for USB devices that are not plugged in. Use the BIOS "Boot Override" to boot a USB stick.

## Graphics (WhateverXe + `patches/WhateverXe-0.7.0-onb4.patch`)

Functional changes in the patch (on by default unless noted):

- **eDP link rate**: the panel is eDP 1.4 with a link-rate table; clamp to the rates it actually lists.
- **80 EU / 6-bank** GT configuration for the 80EU part.
- **Backlight PWM from VBT**: the panel wants 200 Hz, active-low (`period 96000 @ 19.2 MHz`); Apple hard-codes 1080 Hz non-inverted.
- **DDI A HPD enable after S3**: `SHOTPLUG_CTL_DDI` bit 3 is cleared in S3 and Apple only restores it with a Camellia TCON.
- **PHY A IREFGEN / DCC on wake**, **eDP max lanes**, **TPS3**.
- **TGL DPLL CFGCR address fix**: Apple writes DPLL0 config to the Ice Lake addresses after S3.
- **Link-training retry** (`-onb4ltretry`): one random lane sometimes fails EQ (no symbol lock) at boot, S3 wake or DPMS; retrying works.
- **Render register restore after GPU reset**: Apple's reset list is the Gen9 one (19 registers); L3CC and others are lost after a reset.
- Diagnostics exported to ioreg (wake trace, AUX trace, PHY dump, GT register snapshots, scheduler trace); parsers are in `tools/`.

Other display fixes:

- **Brightness did nothing**: the panel EDID says year 2002. For years before 2007 AppleBacklight takes the old non-linear path and never
  publishes `linear-brightness`, so CoreDisplay never writes `bklt`. Fix: `AAPL00,override-no-connect` with the same EDID, year 2020
  (byte 17) and fixed checksum.
- **Screen never came back after display sleep**: the Apple TGL framebuffer enters hardware DC6 and rewrites the DMC's AUX programming;
  after that the panel AUX channel stays BUSY. `-nodisplaysleepDC6` avoids it. Powering the AUX well off instead hangs the machine.
- **Video**: hardware decode is bit-exact; only colour conversion is broken (no Gen12 VEBOX renderer in the VA driver). AppleGVA swallows
  the error. `tools/va-shim/` wraps the driver and converts on the CPU (vImage).

## Input (VoodooI2C CI build `6be653a2`)

- VoodooI2C 2.9.1 release does not support Tiger Lake I2C/GPIO; the master CI build does.
- **Touchpad got no input at all**: VoodooI2CHID's `SYNA3602` personality forces a hard-coded descriptor meant for a SIPODEV SP1064
  (firmware without a descriptor). This touchpad (`0911:5288`) reports its own. `build-efi.py` removes that personality so the generic
  `PNP0C50` driver reads the real descriptor.
- **Touchpad GPIO interrupt stalled after ~0.3 s** (input stopped, cursor barely moved): `IOInterruptEventSource` asks `getInterruptType` *before* `registerInterrupt`,
  and VoodooGPIO only records the type in `registerInterrupt` → it answers Edge, the source does not mask, but the pad is
  Level/ActiveLow and re-fires immediately. Kernel patch: `VoodooGPIOIntel::getInterruptType` always returns Level
  (only the two I2C devices use GPIO interrupts here). Then `force-polling` can be removed for I2C0 and I2C1.
- **Touchscreen ignored taps 5 to 14 after idle**: the Goodix `GXTP7386` sends incrementing tracking IDs (1, 2, 3, …, wrapping at 0x78)
  as Contact Identifier, not slot numbers. `VoodooI2CMultitouchHIDEventDriver::handleDigitizerReport` computes
  `actual_index = id / 5` (5 contacts per report) and switches to that wrapper: IDs 5–9 land in the second finger wrapper (the touchscreen
  driver only looks at `transducers[0..contact_count]`), 10–14 in the stylus wrapper, ≥15 fall back to wrapper 0. Linux's hid-multitouch
  matches slots by ID and is fine. Kernel patch: `je` → `jmp` so the driver always uses the current report's wrapper.
  `tools/hidsniff/hidrate.c` logs raw reports with timestamps; that is how the report stream was shown to be intact.

## Power

- **No battery in macOS**: `ADP1._STA` returns present only when `ECON == 1`; this firmware has `ECON = 0` (Linux shows no AC either),
  and SMCBatteryManager needs both battery and AC. `SSDT-ADP1` + rename the whole `_STA` method to `XSTA`.
- **Brightness keys**: Fn+F4/F5 are EC queries `_Q04`/`_Q05` (ACPI video notifications, not scan codes).
  `SSDT-BRTKEY` + renames notify `PS2K` with `0x0405`/`0x0406`.
- **Clock 8 hours fast in macOS**: Fedora was set to keep the RTC in local time. `timedatectl set-local-rtc 0` in Linux.
- **Hibernation** (unsolved). Findings so far:
  1. With `standby 0` the platform chooses DeepIdle (`sleep type 7`) and never writes the image; tests need `standby 1`.
  2. With `HibernateMode=NVRAM` the first OpenCore that runs consumes the key. Switching to a USB OpenCore from the picker loses it.
  3. The FACS hardware signature changes every boot → `Warn(0x66)`; `ACPI > Quirks > ResetHwSig` fixes it.
  4. After that the image is read (2.1 s) and control passes to the kernel, which then freezes before any user process resumes
     (`DiscardHibernateMap` and `DevirtualiseMmio=false` do not help). The GPU driver's S4 wake path is the main suspect.

## USB

Map in `build-efi.py` (`USB_MAP`, generated as `UTBMap.kext`):

| Port | USB 2 | USB 3 |
|---|---|---|
| Right Type-C | PCH `HS03` | PCH `SS01`/`SS02` (one per orientation, no mux) |
| Left 1 (USB4) | dead on this unit (macOS and Linux) | TXHC `SS01` |
| Left 2 (USB4) | PCH `HS05` | TXHC `SS02` |
| Internal | PCH `HS10` = Bluetooth | |

ACPI `_UPC` marks several of these as USB-A, which is wrong. TXHC only gets ports when UTBMap lists it too.

## Tools

| Tool | What it does |
|---|---|
| `tools/hidsniff/` | `hidsniff`: dump HID reports of a device; `hidrate`: per-report timestamps or reports per second |
| `tools/gpucheck/` | `gpucheck`: Metal compute/render correctness + stress; `vtdecode`: hardware-only VideoToolbox decode; `vtxfer`: VTPixelTransferSession cases |
| `tools/onb4-hang-capture.sh` + plist | LaunchDaemon that saves ioreg when the GPU is reset (`GPURestartSignaled`) |
| `tools/onb4-s3-loop.sh`, `onb4-wake-capture.sh` | Repeated S3 with RTC wake and a GPU check after each wake |
| `tools/onb4-*.py` | Parsers for the diagnostics the patched WhateverXe exports to ioreg (wake/AUX/DPCD/PHY/GT/scheduler traces) |
| `tools/onb4-linux-*.sh` | Register dumps / DPMS loop in Linux (reference values from i915) |
| `tools/va-shim/`, `vabundle.sh`, `patch-tglva.py`, `gvascaler.sh` | Software colour-conversion shim for the WhateverXe-Graphics VA driver and its installer |
| `tools/vadriver-re/` | Helpers used to reverse the VA driver (RTTI, xrefs) |
| `tools/blset` | Set the backlight through IOKit |
| `tools/usbwatch.sh`, `dispwatch.sh` | Watch USB / display events while plugging things in |
| `tools/make-picker-icns.sh` | Build the OpenCanopy icons from SVG |
| `scripts/vbt-edp.py` | Parse the eDP part of the Intel VBT |
