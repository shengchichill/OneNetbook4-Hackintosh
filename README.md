# OneNetbook 4 Hackintosh (macOS Tahoe 26)

OpenCore EFI, ACPI patches, kext patches and debugging tools for the **One-Netbook OneNetbook 4**
(Intel i5-1130G7, Tiger Lake UP4, Iris Xe 80EU `8086:9a40`) running **macOS Tahoe 26.7.2**, dual-booting Fedora.

Daily-driven since November 2026. Graphics are accelerated with [WhateverXe](https://github.com/b00t0x/WhateverXe)
plus a set of local fixes for this machine's eDP panel, backlight and S3 wake (see [`patches/`](patches/)).

> This is a personal project shared as-is. It works on my unit; your BIOS version or panel may differ.
> Read the [known issues](#what-does-not-work) before you rely on it.

## Hardware

| Component | Details | Status |
|---|---|---|
| CPU | i5-1130G7 (4C/8T), spoofed as Ice Lake `0x706E5`, SMBIOS `MacBookPro16,2` | ✅ |
| iGPU | Iris Xe 80EU `8086:9a40`, DVMT fixed at 60 MB | ✅ Metal (WhateverXe + patches) |
| Display | 10.1" eDP 2560×1600 60 Hz | ✅ brightness control, HiDPI |
| Wi-Fi | Intel AX201 (CNVi) | ✅ itlwm + HeliPort |
| Bluetooth | Intel AX201 `8087:0026` | ✅ IntelBluetoothFirmware 2.5.1 (lshbluesky fork) |
| Audio | Realtek ALC269VC | ❌ Tahoe removed AppleHDA (use Bluetooth/USB audio) |
| Keyboard | PS/2 | ✅ incl. Fn brightness keys |
| Touchpad | Synaptics `SYNA3602` on I2C0 | ✅ VoodooI2C, GPIO interrupt, PTP gestures |
| Touchscreen | Goodix `GXTP7386` on I2C1 | ✅ VoodooI2C, GPIO interrupt (pen not tested) |
| Storage | Phison E13 NVMe | ✅ |
| Battery / AC | EC `BAT0`, `ADP1` | ✅ (SSDT-ADP1 + ECEnabler) |
| USB-C right (USB 3) | PCH xHCI `8086:a0ed` | ✅ 5 Gbps |
| USB-C left ×2 (USB4) | TCSS xHCI | ✅ USB 3 5 Gbps, DP Alt Mode; ❌ Thunderbolt/USB4 tunnelling; left-1 USB 2 pins are dead on this unit (also in Linux) |
| Sleep (S3) | BIOS exposes S3 | ✅ (see notes) |
| Hibernation | | ❌ freezes after the kernel restores the image |
| Accelerometer | Bosch BMI323 | ❌ no driver, no auto-rotate |
| Camera / fingerprint | not present / not detected | — |

BIOS: AMI 5.19 (2021-07-15). CFG Lock is on (`AppleXcpmCfgLock`), Secure Boot off.

## What works

- Graphics acceleration (Metal), internal panel at native resolution, external displays on both left USB-C ports
- Brightness slider and Fn+F4/F5 (EDID year override + VBT PWM fix, see notes)
- H.264 / HEVC 8/10-bit **hardware decode** (needs the optional VA shim in [`tools/va-shim/`](tools/va-shim/); colour conversion runs on the CPU)
- Touchpad and touchscreen on GPIO interrupts, including a fix for touchscreen taps being dropped after idle
- Wi-Fi, Bluetooth (headphones tested), battery percentage, AC status
- S3 sleep / wake from the menu and with the lid (lid needs `SSDT-LID`, see notes), display sleep
- OpenCanopy boot picker (GoldenGate theme, custom Apple/Fedora icons) with a Fedora entry

## What does not work

- **Internal audio** — macOS Tahoe has no AppleHDA. Not planned.
- **Hibernation** (`hibernatemode 25`) — the image is written and read back, then the machine freezes. Keep `hibernatemode 0` and `standby 0`.
- **Video colour conversion on the GPU** — WhateverXe-Graphics' VA driver has no Gen12 VEBOX renderer; the VA shim does it in software.
  Platform processes (Safari's WebKit GPU process, Music, WindowServer) refuse the ad-hoc signed shim and use their own software path.
  HEVC/HDR videos in the Music app do not play.
- **Rare GPU hangs** — seen a few times early on, not reproducible in 200+ later S3 cycles. [`tools/onb4-hang-capture.sh`](tools/onb4-hang-capture.sh) can capture state automatically.
- S3 wake relies on a link-training retry (`-onb4ltretry`): one random eDP lane occasionally fails symbol lock; root cause unknown.

## Using the EFI

### Option A — prebuilt EFI (Releases)

1. Download `EFI-OneNetbook4-*.zip` from [Releases](../../releases).
2. **Generate your own SMBIOS** (`MacBookPro16,2`) with [GenSMBIOS](https://github.com/corpnewt/GenSMBIOS) or `macserial`,
   and fill `PlatformInfo > Generic` (`SystemSerialNumber`, `MLB`, `SystemUUID`, `ROM`). The release ships OpenCore's placeholder values.
3. The `Fedora` entry under `Misc > Entries` is disabled. To use it, set `Path` to the full device path of your
   `\EFI\fedora\shimx64.efi` (from `efibootmgr -v` in Linux) and set `Enabled` to true.
4. After installing macOS, install [WhateverXe-Graphics](https://github.com/b00t0x/WhateverXe-Graphics) (Metal driver) and
   [HeliPort](https://github.com/OpenIntelWireless/HeliPort) (Wi-Fi UI).
   Match the Graphics version to the kext: WhateverXe 0.8.3 (current `main`) → Graphics **0.4.4**;
   WhateverXe 0.7.0 (release `v2026.11.20`) → Graphics 0.4.0.

### Option B — build it yourself

```bash
bash scripts/fetch-deps.sh          # OpenCore 1.0.8 and kexts into build/deps, extracted to build/extract
# manual items (fetch-deps prints what is missing):
#  - WhateverXe 0.8.3 (b00t0x/WhateverXe @ f26a368) + patches/WhateverXe-0.8.3-onb4.patch, Xcode build
#    -> build/extract/WhateverXe-0.8.3-onb4-RELEASE/WhateverXe.kext
#  - IntelBluetoothFirmware 2.5.1 (lshbluesky fork) -> build/extract/IntelBluetooth-v2.5.1/
#  - OcBinaryData (acidanthera/OcBinaryData) cloned to build/deps/OcBinaryData
python3 scripts/build-efi.py          # daily build -> EFI/       (RELEASE, Apple logo boot)
python3 scripts/build-efi.py --usb    # debug build -> EFI-usb/   (DEBUG, -v, 20 s timeout, log files on the ESP)
python3 scripts/build-efi.py --public # release zip -> EFI-public/ (placeholder SMBIOS, Fedora entry off)
```

[`scripts/build-efi.py`](scripts/build-efi.py) is the single source of truth: it starts from OpenCore's `Sample.plist` and sets
every value with a comment explaining why (comments are in Traditional Chinese). On first run it generates an SMBIOS into
`secrets/smbios.json` (git-ignored). Machine-specific paths go in `secrets/machine.json`:

```json
{ "fedora_shim": "PciRoot(0x0)/Pci(0x1D,0x0)/Pci(0x0,0x0)/NVMe(0x1,<EUI>)/HD(1,GPT,<ESP PARTUUID>,0x800,0x12C000)/\\EFI\\fedora\\shimx64.efi" }
```

The Kernel > Patch entries for VoodooGPIO / VoodooI2CHID match the binaries of VoodooI2C CI build `6be653a2`
(2.9.1 release does not support Tiger Lake I2C/GPIO). With another VoodooI2C build, re-check the find patterns.

### Boot flags

| boot-arg | Purpose |
|---|---|
| `-igfxdvmt` + `framebuffer-stolenmem` | 60 MB DVMT (the BIOS has no DVMT setting) |
| `-allow3d -disablegfxfirmware` | WhateverXe |
| `-nodisplaysleepDC6` | Apple TGL framebuffer: do not enter DC6 on display sleep (otherwise the panel's AUX channel stops answering and the screen never comes back) |
| `-onb4ltretry` | patched WhateverXe: retry eDP link training (S3 wake) |
| `-onb4noccs` | patched WhateverXe 0.8.3: disable CCS multi-context (added while chasing GPU hangs, see notes) |
| `-btlfxallowanyaddr` | BlueToolFixup: accept the AX201 address on Tahoe |
| `keepsyms=1 debug=0x100` | readable panics |

When booting gets stuck, hold **Cmd+V** (Win+V) in the picker before choosing macOS to get a verbose boot.

## Repository layout

| Path | Contents |
|---|---|
| `ACPI/` | SSDTs (`.dsl` source + compiled `.aml`): ADP1, AWAC, BRTKEY, EC-USBX, GPRW, LID, PLUG, PMC, PNLF |
| `patches/` | WhateverXe 0.8.3 patch (current) and the older 0.7.0 patch (functional fixes + diagnostics), each with its base commit |
| `kexts/` | `XHCI-unsupported.kext` (RehabMan injector with `0xa0ed8086` added) |
| `resources/picker/` | Apple / Fedora icons for OpenCanopy (+ SVG sources) |
| `scripts/` | `build-efi.py`, `fetch-deps.sh`, `vbt-edp.py` (VBT eDP parser), `onb4-hwdump.sh` (hardware dump in Linux) |
| `tools/` | Debugging tools used during the project (see [docs/NOTES.md](docs/NOTES.md#tools)) |
| `docs/NOTES.md` | Technical notes: root causes and fixes found along the way |

## Credits

- [acidanthera](https://github.com/acidanthera) — OpenCore, Lilu, VirtualSMC, AppleALC, VoodooPS2, NVMeFix, RestrictEvents, HibernationFixup, BrcmPatchRAM
- [b00t0x](https://github.com/b00t0x) — WhateverXe, WhateverXe-Graphics, AMFIPass Mod
- [VoodooI2C](https://github.com/VoodooI2C/VoodooI2C), [ECEnabler](https://github.com/1Revenger1/ECEnabler), [USBToolBox](https://github.com/USBToolBox/kext)
- [OpenIntelWireless](https://github.com/OpenIntelWireless) — itlwm, HeliPort; lshbluesky — IntelBluetoothFirmware Tahoe fork
- RehabMan — XHCI-unsupported injector
- Reference EFIs from other Tiger Lake laptops (Dell Latitude 5520, Lenovo Yoga Slim 7, Samsung Galaxy Book) and the Iris Xe Dell XPS 13 Plus Tahoe project

## License

Scripts, SSDTs, tools and the WhateverXe patch in this repository: BSD 3-Clause (see [LICENSE](LICENSE)).
Third-party binaries in the release zip keep their own licenses.
