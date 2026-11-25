#!/usr/bin/env python3
"""組裝 OneNetbook 4 的 OpenCore EFI 到 EFI/（產物，不進 git；本腳本才是設定的來源）。

前置：bash scripts/fetch-deps.sh；ACPI/*.aml 已編譯。
SMBIOS 序號存在 secrets/smbios.json（第一次自動產生，之後沿用，不進 git）。
"""
import json, os, plistlib, secrets, shutil, subprocess, sys, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "build/extract"
OC = X / "OpenCore-1.0.8-RELEASE"
# 2026-11-20 收尾：兩種產物
#   python3 scripts/build-efi.py        → EFI/      日常版（內建 ESP）：RELEASE .efi、不加 -v（Apple logo 開機）、Timeout 5、不寫 log
#   python3 scripts/build-efi.py --usb  → EFI-usb/  除錯版（USB 測試碟）：DEBUG .efi、-v、Timeout 20、Target 0x41（log 寫到 USB 根目錄）
# 兩者其餘設定完全相同。日常版開機卡住時，在 OC 選單按住 Cmd+V 再選 macOS 可臨時加 -v（PollAppleHotKeys）。
#   python3 scripts/build-efi.py --public → EFI-public/  公開版：同日常版，但不讀 secrets/（SMBIOS 用 Sample.plist 佔位值、Fedora 項目停用）
USB_VARIANT = "--usb" in sys.argv[1:]
PUBLIC = "--public" in sys.argv[1:]
assert not (USB_VARIANT and PUBLIC), "--usb and --public are exclusive"
OC_FLAVOR = "DEBUG" if USB_VARIANT else "RELEASE"
OC_EFI = X / f"OpenCore-1.0.8-{OC_FLAVOR}"
OUT = ROOT / ("EFI-usb" if USB_VARIANT else "EFI-public" if PUBLIC else "EFI")
# 機器相關的值（不進 git）：{"fedora_shim": "<完整 device path 到 \\EFI\\fedora\\shimx64.efi>"}
# 取得方式見 README（Fedora 下 efibootmgr -v 的 Fedora 項目）。沒有這個檔案（或 --public）→ Fedora 項目停用。
MACHINE = ROOT / "secrets/machine.json"
FEDORA_SHIM_PLACEHOLDER = "PciRoot(0x0)/Pci(0x1D,0x0)/Pci(0x0,0x0)/NVMe(0x1,00-00-00-00-00-00-00-00)/HD(1,GPT,00000000-0000-0000-0000-000000000000,0x800,0x12C000)/\\EFI\\fedora\\shimx64.efi"


def machine():
    if PUBLIC or not MACHINE.exists():
        return {}
    return json.loads(MACHINE.read_text())
SMBIOS_MODEL = "MacBookPro16,2"  # Ice Lake 13"，最接近 Tiger Lake U 且 Tahoe 仍支援

USE_UTBMAP = True
# 2026-11-19：觸控板 I2C0 改走 GPIO 中斷的測試。VoodooI2CHID 的 IOInterruptEventSource 在 registerInterrupt「之前」
# 呼叫 getInterruptType，那時 VoodooGPIO 還沒 setInterruptTypeForPin（在 nub 的 registerInterrupt 裡才設）→ 回 Edge
# → 事件源不自動 mask，但 pad 設成 Level/ActiveLow → 清 GPI_IS 後立刻又起 → 疑中斷風暴/卡死。
# True = Kernel Patch 讓 VoodooGPIOIntel::getInterruptType 一律回 Level（只有觸控板一個 pin 用中斷），並拿掉 I2C0 force-polling。
I2C0_GPIO_IRQ = True
# 2026-11-20：觸控螢幕 I2C1（GXTP7386）也改 GPIO 中斷的測試。ACPI 同樣是 GpioInt(Level, ActiveLow, Shared)（Fedora 下 GPIO 337），
# 上面的 VoodooGPIO Kernel Patch（一律回 Level）也適用 → 只需拿掉 I2C1 force-polling。需 I2C0_GPIO_IRQ=True（Kernel Patch 由它加入）。
I2C1_GPIO_IRQ = True
# 2026-11-20：觸控螢幕「閒置後第 5～14 次觸碰沒反應」修正（hidrate 逐筆紀錄＋VoodooI2CHID 27277936 原始碼確認）。
# GXTP7386（Goodix）的 Contact Identifier 是遞增的追蹤編號（1,2,3…，閒置後重來），不是 0～9 的插槽編號；
# 報告每筆 5 指、Contact Count Maximum 10 → 2 個 finger wrapper ＋ 1 個 stylus wrapper。
# VoodooI2CMultitouchHIDEventDriver::handleDigitizerReport 用 actual_index = 編號/5 換 wrapper：
#   編號 5～9 → wrapper 1（觸控螢幕驅動只在 transducers[0..contact_count] 找手指 → 找不到 → 丟給 VoodooInput 當手勢）
#   編號 10～14 → wrapper 2 ＝ stylus wrapper；≥15 → 不存在、退回 wrapper 0（又正常）。
# Fedora hid-multitouch 用編號配對 slot，所以正常。這台報告一定依序送 → 一律用 current_report-1 就對。
# Patch：handleDigitizerReport 的 `cmp esi,eax; je`（actual_index == current_report-1 才不換）→ `jmp`（永遠不換）。
TS_CONTACT_ID_FIX = True
# 2026-11-24：闔蓋不睡眠修正（2026-11-25 起預設開，內建 ESP 已部署）。EC 事件 _Q0C/_Q0D 與 LID0._LID 呼叫的 ECRD 在 macOS ACPICA
# 回 AE_AML_OPERAND_TYPE 中止，Notify(LID0) 沒送出。SSDT-LID 在 Darwin 下直接讀 LSTE 並通知 LID0。見 ACPI/SSDT-LID.dsl。
LID_FIX = True
LID_SSDT = "SSDT-LID.aml"
# (Comment, Find, Replace)；find 含 method 標頭，DSDT 內各唯一（hwdump 20261103 dsdt.dat 驗證）
LID_PATCHES = [
    ("_Q0C to XQ0C lid event (pairs with SSDT-LID)", "142b5f51304300", "142b5851304300"),
    ("_Q0D to XQ0D lid event (pairs with SSDT-LID)", "142b5f51304400", "142b5851304400"),
    ("LID0._LID to XLID (pairs with SSDT-LID)", "14105f4c494400", "1410584c494400"),
]


def lid_acpi_patches():
    return [{"Base": "", "BaseSkip": 0, "Comment": c, "Count": 1, "Enabled": True,
             "Find": bytes.fromhex(f), "Limit": 0, "Mask": b"", "OemTableId": b"",
             "Replace": bytes.fromhex(r), "ReplaceMask": b"", "Skip": 0, "TableLength": 0,
             "TableSignature": b"DSDT"} for c, f, r in LID_PATCHES]

# ---- kext：(來源資料夾, BundlePath, Enabled, 註解)；順序即載入順序 ----
KEXTS = [
    ("Lilu-1.7.2-RELEASE", "Lilu.kext", True, ""),
    ("VirtualSMC-1.3.8-RELEASE/Kexts", "VirtualSMC.kext", True, ""),
    ("VirtualSMC-1.3.8-RELEASE/Kexts", "SMCBatteryManager.kext", True, ""),
    ("VirtualSMC-1.3.8-RELEASE/Kexts", "SMCProcessor.kext", True, ""),
    ("WhateverXe-0.8.3-onb4-RELEASE", "WhateverXe.kext", True, "Iris Xe 9A40, WEX 0.8.3 + local patch (patches/WhateverXe-0.8.3-onb4.patch, b857865); pairs with Graphics 0.4.4 in /Library; -onb4noccs"),
    ("AMFIPass-v1.4.1-Mod-RELEASE", "AMFIPass.kext", True, "Mod build required by WhateverXe"),
    ("ECEnabler-1.0.6-RELEASE", "ECEnabler.kext", True, "16-bit EC battery fields"),
    ("AppleALC-1.9.8-RELEASE", "AppleALC.kext", True, "ALC269VC"),
    ("HibernationFixup-1.5.4-RELEASE", "HibernationFixup.kext", True, "hibernate key in NVRAM"),
    # RehabMan OS-X-USB-Inject-All 的 XHCI-unsupported（只有 Info.plist），IOPCIPrimaryMatch 加了 0xa0ed8086（本機 PCH xHCI）
    ("kexts", "XHCI-unsupported.kext", True, "PCH xHCI a0ed"),
    ("USBToolBox-1.2.0-RELEASE", "USBToolBox.kext", True, ""),
    # UTBMap 尚未上機驗證：先用 UTBDefault，等修睡眠時把 USE_UTBMAP 改 True 一起驗證（兩個 kext 都會複製）
    ("USBToolBox-1.2.0-RELEASE", "UTBDefault.kext", not USE_UTBMAP, "temporary, replace with UTBMap"),
    (None, "UTBMap.kext", USE_UTBMAP, "generated from USB_MAP below"),
    ("VoodooPS2Controller-2.3.7-RELEASE", "VoodooPS2Controller.kext", True, "keyboard only"),
    (None, "VoodooPS2Controller.kext/Contents/PlugIns/VoodooPS2Keyboard.kext", True, ""),
    (None, "VoodooPS2Controller.kext/Contents/PlugIns/VoodooPS2Mouse.kext", False, ""),
    (None, "VoodooPS2Controller.kext/Contents/PlugIns/VoodooPS2Trackpad.kext", False, ""),
    (None, "VoodooPS2Controller.kext/Contents/PlugIns/VoodooInput.kext", False, "duplicate of VoodooI2C copy"),
    # VoodooI2C 依賴自己的 plugin，plugin 先載入（檔案由下方 VoodooI2C.kext 那筆一起複製）
    (None, "VoodooI2C.kext/Contents/PlugIns/VoodooGPIO.kext", True, ""),
    (None, "VoodooI2C.kext/Contents/PlugIns/VoodooI2CServices.kext", True, ""),
    (None, "VoodooI2C.kext/Contents/PlugIns/VoodooInput.kext", True, ""),
    # VoodooI2C master 6be653a2 的 CI 編譯檔：2.9.1 release 不支援 Tiger Lake I2C/GPIO（見 fetch-deps.sh）
    ("VoodooI2C-6be653a2", "VoodooI2C.kext", True, "master 6be653a2, Tiger Lake"),
    ("VoodooI2C-6be653a2", "VoodooI2CHID.kext", True, "SYNA3602 touchpad + GXTP7386 touchscreen"),
    ("itlwm_v2.3.0_stable.kext", "itlwm.kext", True, "AX201, use with HeliPort"),
    ("BrcmPatchRAM-2.7.2-RELEASE", "BlueToolFixup.kext", True, ""),
    ("IntelBluetooth-v2.5.1", "IntelBluetoothFirmware.kext", True, "lshbluesky fork, Tahoe support"),
    ("IntelBluetooth-v2.5.1", "IntelBTPatcher.kext", True, "lshbluesky fork, Tahoe support"),
    ("NVMeFix-1.1.3-RELEASE", "NVMeFix.kext", True, ""),
    ("RestrictEvents-1.1.6-RELEASE", "RestrictEvents.kext", True, ""),
]

# ---- USB 對應（USBToolBox UTBMap）：2026-11-05 實測（tools/usbwatch.sh，build/logs/usb-20261105/）----
# 規格：左側 2 個 USB4 Type-C（TCSS/TXHC，可 PD、影像），右側 1 個 USB 3.0 Type-C（PCH）。
# 實測：右側 = HS03 + PCH SS01/SS02（依正反面分別接，無 mux → connector 10），5 Gbps ✅；
# 左 2 = USB2 走 PCH HS05、USB3 走 TXHC SS02（0d3）。左 1 = USB3 走 TXHC SS01（0d2）；
# 左 1 的 USB2：2026-11-20 用 USB3 hub（鍵盤／滑鼠接收器在 hub 的 USB2 端）實測，macOS 與 Fedora 都完全沒出現
# （PCH、TXHC 都沒有）→ 硬體／韌體層不通，不是 macOS 問題。ACPI（RUCC 接頭 1）說是 HS01，保留但沒作用。HS10 = 內建 AX201 藍牙。
# ACPI _UPC 把 HS02/HS04/SS01/SS02 標成 USB-A，與實機不符，不採用。
# TXHC：2026-11-19 實測「不做對應」不是維持原生——UTBDefault（IOPCIClassMatch 比對所有 xHCI）才讓 TXHC 有 port；
# 只放 XHCI 的 UTBMap 部署後 TXHC 一個 port 都沒有（開機碟從 TXHC 0d300000 USB3 掉到 HS05 USB2）。
# → 照 UTBDefault 下看到的 5 個 port 原樣列出（0d1 = USB2、0d2～0d5 = USB3；左 1 = 0d2、左 2 = 0d3，2026-11-19 macOS／Fedora 都實測 5 Gbps），0d4/0d5 沒接頭用到。
# UsbConnector：9 = Type-C 有 switch、10 = Type-C 無 switch、255 = 內建
USB_MAP = {
    "XHCI": {  # PCH xHCI 8086:a0ed，以 ACPI 名稱比對
        "HS01": (1, 9, "left 1st Type-C USB2 per ACPI; never connects (macOS and Linux, 2026-11-20)"),
        "HS03": (3, 10, "right Type-C USB2"),
        "HS05": (5, 9, "left 2nd Type-C USB2 (its USB3 is on TXHC)"),
        "HS10": (10, 255, "internal AX201 Bluetooth"),
        "SS01": (13, 10, "right Type-C USB3, one orientation"),
        "SS02": (14, 10, "right Type-C USB3, other orientation"),
    },
    "TXHC": {  # TCSS xHCI（左側 USB4），port 編號 = ioreg location 第 3 個 byte
        "HS01": (1, 9, "TCSS USB2 port (AppleUSB20XHCIPort@0d100000)"),
        "SS01": (2, 9, "left 1st Type-C USB3 (2026-11-19)"),
        "SS02": (3, 9, "left 2nd Type-C USB3 (boot USB, 2026-11-19)"),
        "SS03": (4, 9, "TCSS USB3 port 0d400000"),
        "SS04": (5, 9, "TCSS USB3 port 0d500000"),
    },
}

SSDTS = ["SSDT-PLUG.aml", "SSDT-EC-USBX.aml", "SSDT-AWAC.aml",
         "SSDT-PMC.aml", "SSDT-PNLF.aml", "SSDT-GPRW.aml", "SSDT-ADP1.aml",
         "SSDT-BRTKEY.aml"] + ([LID_SSDT] if LID_FIX else [])
DRIVERS = ["OpenRuntime.efi", "OpenHfsPlus.efi", "ResetNvramEntry.efi", "OpenCanopy.efi",
           "FirmwareSettingsEntry.efi"]  # 選單按空白鍵顯示「進 BIOS」（2026-11-19）
# OpenCanopy 圖形選單資源（acidanthera/OcBinaryData，使用者 2026-11-19 clone 到 build/deps/）
OCBIN = ROOT / "build/deps/OcBinaryData/Resources"
PICKER_THEME = "Acidanthera/GoldenGate"   # 另有 Chardonnay、Syrah

# -btlfxallowanyaddr：BlueToolFixup 放行 Intel BT 位址（AX201 在 Tahoe 位址 NULL、State Off，2026-11-05）
BOOT_ARGS = ("-v " if USB_VARIANT else "") + "keepsyms=1 debug=0x100 -allow3d -disablegfxfirmware -igfxdvmt -btlfxallowanyaddr -nodisplaysleepDC6 -onb4ltretry -onb4noccs"  # -onb4noccs：WEX 0.8.3 本地 patch 的開關，停用 CCS multi-context（2026-11-25 內建部署）


def smbios():
    f = ROOT / "secrets/smbios.json"
    if f.exists():
        return json.loads(f.read_text())
    ms = OC / "Utilities/macserial/macserial"
    line = subprocess.check_output([str(ms), "-m", SMBIOS_MODEL, "-n", "1"], text=True).strip()
    serial, mlb = [s.strip() for s in line.split("|")]
    rom = bytearray(secrets.token_bytes(6)); rom[0] = (rom[0] | 0x02) & 0xFE  # 本地管理、單播
    d = {"model": SMBIOS_MODEL, "serial": serial, "mlb": mlb,
         "uuid": str(uuid.uuid4()).upper(), "rom": rom.hex()}
    f.parent.mkdir(exist_ok=True); f.write_text(json.dumps(d, indent=2))
    return d


def write_utbmap(kext):
    """依 USB_MAP 產生 UTBMap.kext（格式同 USBToolBox tool 的 build_kext）。"""
    le32 = lambda n: n.to_bytes(4, "little")
    pers = {}
    for ctrl, ports in USB_MAP.items():
        pers[ctrl] = {
            "CFBundleIdentifier": "com.dhinakg.USBToolBox.kext",
            "IOClass": "USBToolBox",
            "IOMatchCategory": "USBToolBox",
            "IOProviderClass": "IOPCIDevice",
            "IONameMatch": ctrl,
            "IOProviderMergeProperties": {
                "ports": {name: {"port": le32(idx), "UsbConnector": conn, "#comment": c}
                          for name, (idx, conn, c) in ports.items()},
                "port-count": le32(max(idx for idx, _, _ in ports.values())),
            },
        }
    info = {
        "CFBundleDevelopmentRegion": "English", "CFBundleGetInfoString": "v1.1",
        "CFBundleIdentifier": "com.dhinakg.USBToolBox.map", "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "UTBMap", "CFBundlePackageType": "KEXT", "CFBundleShortVersionString": "1.1",
        "CFBundleSignature": "????", "CFBundleVersion": "1.1",
        "IOKitPersonalities": pers,
        "OSBundleLibraries": {"com.dhinakg.USBToolBox.kext": "1.0.0"},
        "OSBundleRequired": "Root",
    }
    (kext / "Contents").mkdir(parents=True)
    plistlib.dump(info, open(kext / "Contents/Info.plist", "wb"), sort_keys=True)


def kext_entry(bundle, enabled, comment):
    exe = ""
    info = OUT / "OC/Kexts" / bundle / "Contents/Info.plist"
    p = plistlib.load(open(info, "rb"))
    if (OUT / "OC/Kexts" / bundle / "Contents/MacOS").exists():
        exe = "Contents/MacOS/" + p["CFBundleExecutable"]
    return {"Arch": "x86_64", "BundlePath": bundle, "Comment": comment, "Enabled": enabled,
            "ExecutablePath": exe, "MaxKernel": "", "MinKernel": "",
            "PlistPath": "Contents/Info.plist"}


def main():
    marker = OUT / ".generated-by-build-efi"
    if OUT.exists() and any(OUT.iterdir()):
        if not marker.exists():
            raise SystemExit(f"{OUT} 有不是本腳本產生的內容，請手動確認後再執行")
        shutil.rmtree(OUT)  # 只會刪到帶有 marker 的 EFI/（本腳本的產物）
    (OUT / "BOOT").mkdir(parents=True)
    marker.write_text("此資料夾由 scripts/build-efi.py 產生，重建時會整個覆蓋\n")
    src = OC_EFI / "X64/EFI"
    shutil.copy(src / "BOOT/BOOTx64.efi", OUT / "BOOT/")
    for d in ("ACPI", "Drivers", "Kexts", "Tools", "Resources"):
        (OUT / "OC" / d).mkdir(parents=True)
    shutil.copy(src / "OC/OpenCore.efi", OUT / "OC/")
    for drv in DRIVERS:
        shutil.copy(src / "OC/Drivers" / drv, OUT / "OC/Drivers/")
    shutil.copy(src / "OC/Tools/OpenShell.efi", OUT / "OC/Tools/")
    # 只帶選用的主題、字型、標籤（Audio 6.8 MB 不帶，PickerAudioAssist 關）
    shutil.copytree(OCBIN / "Image" / PICKER_THEME, OUT / "OC/Resources/Image" / PICKER_THEME)
    # 主題沒有 Apple／Linux 圖示 → 自製純 logo（tools/make-picker-icns.sh，2026-11-20）：
    # macOS 自動項目 flavour Apple → Apple.icns；Fedora 項目（Flavour Fedora:Linux）→ Fedora.icns
    for icns in ("Apple.icns", "Fedora.icns"):
        shutil.copy(ROOT / "resources/picker" / icns, OUT / "OC/Resources/Image" / PICKER_THEME)
    for d in ("Font", "Label"):
        shutil.copytree(OCBIN / d, OUT / "OC/Resources" / d)
    for s in SSDTS:
        shutil.copy(ROOT / "ACPI" / s, OUT / "OC/ACPI/")

    for folder, bundle, _, _ in KEXTS:
        if folder:
            base = ROOT if folder == "kexts" else X
            shutil.copytree(base / folder / bundle, OUT / "OC/Kexts" / bundle)

    # VoodooI2CHID 的 SYNA3602 override 寫死 SIPODEV SP1064 的 HID/report descriptor
    # （Linux i2c-hid-dmi-quirks 給「韌體沒提供 descriptor」的機型用）。ONB4 這顆
    # 0911:5288 會回報自己的 descriptor（Linux Version=0x0100，override 是 0x0006），
    # 套 override 後完全收不到 input report。拿掉這個 personality，改由通用
    # VoodooI2CHIDDevice（compatible PNP0C50）讀真實 descriptor。
    hid_info = OUT / "OC/Kexts/VoodooI2CHID.kext/Contents/Info.plist"
    p = plistlib.load(open(hid_info, "rb"))
    if p["IOKitPersonalities"].pop("VoodooI2CHIDSYNA3602Device", None) is None:
        raise SystemExit("VoodooI2CHID 找不到 VoodooI2CHIDSYNA3602Device personality，確認 kext 版本")
    plistlib.dump(p, open(hid_info, "wb"))

    write_utbmap(OUT / "OC/Kexts/UTBMap.kext")

    cfg = plistlib.load(open(OC / "Docs/Sample.plist", "rb"))

    # ---- ACPI ----
    cfg["ACPI"]["Add"] = [{"Comment": s, "Enabled": True, "Path": s} for s in SSDTS]
    cfg["ACPI"]["Delete"] = []
    cfg["ACPI"]["Patch"] = [{
        "Base": "", "BaseSkip": 0, "Comment": "GPRW to XPRW (pairs with SSDT-GPRW)", "Count": 0,
        "Enabled": True, "Find": bytes.fromhex("4750525702"), "Limit": 0, "Mask": b"",
        "OemTableId": b"", "Replace": bytes.fromhex("5850525702"), "ReplaceMask": b"",
        "Skip": 0, "TableLength": 0, "TableSignature": b""}, {
        # ADP1._STA 只在 ECON==1 回 0x0F，這台 ECON=0 → 沒有 AC → SMCBatteryManager 不啟動。
        # find 是整個 _STA method（含 ECON 判斷），DSDT 內唯一。配對 SSDT-ADP1。
        "Base": "", "BaseSkip": 0, "Comment": "ADP1._STA to XSTA (pairs with SSDT-ADP1)", "Count": 1,
        "Enabled": True, "Find": bytes.fromhex("14135f53544100a00a9345434f4e01a40a0fa400"), "Limit": 0,
        "Mask": b"", "OemTableId": b"", "Replace": bytes.fromhex("14135853544100a00a9345434f4e01a40a0fa400"),
        "ReplaceMask": b"", "Skip": 0, "TableLength": 0, "TableSignature": b"DSDT"}]
    # 亮度鍵 EC 事件 _Q04（調暗）/_Q05（調亮）改名，配對 SSDT-BRTKEY（find 含 method 標頭，DSDT 內各唯一）
    for q, cmt in (("04", "brightness down"), ("05", "brightness up")):
        cfg["ACPI"]["Patch"].append({
            "Base": "", "BaseSkip": 0, "Comment": f"_Q{q} to XQ{q} {cmt} (pairs with SSDT-BRTKEY)", "Count": 1,
            "Enabled": True, "Find": bytes.fromhex("14165f5130" + q.encode().hex()[2:] + "00"), "Limit": 0,
            "Mask": b"", "OemTableId": b"", "Replace": bytes.fromhex("1416585130" + q.encode().hex()[2:] + "00"),
            "ReplaceMask": b"", "Skip": 0, "TableLength": 0, "TableSignature": b"DSDT"})
    if LID_FIX:
        cfg["ACPI"]["Patch"] += lid_acpi_patches()

    # ---- Booter（參考 XPS13Plus Tahoe 設定，Tiger Lake 適用）----
    # DevirtualiseMmio 不可動到 PCIe ECAM 與 flash 區段，否則停在 EXITBS:START（2026-11-03 實測）
    # 位址來自 hwdump（MCFG base 0xC0000000 256MB；dmesg efi MMIO 0xFF000000 16MB），與 XPS13Plus 相同
    cfg["Booter"]["MmioWhitelist"] = [
        {"Address": 0xC0000000, "Comment": "PCIe ECAM (MCFG) 256MB", "Enabled": True},
        {"Address": 0xFF000000, "Comment": "Firmware flash 16MB", "Enabled": True},
    ]
    cfg["Booter"]["Patch"] = []
    bq = cfg["Booter"]["Quirks"]
    for k in ("AvoidRuntimeDefrag", "DevirtualiseMmio", "EnableSafeModeSlide", "FixupAppleEfiImages",
              "ProtectUefiServices", "ProvideCustomSlide", "RebuildAppleMemoryMap",
              "SyncRuntimePermissions"):
        bq[k] = True
    for k in ("EnableWriteUnprotector", "SetupVirtualMap", "ProtectMemoryRegions"):
        bq[k] = False

    # ---- DeviceProperties ----
    cfg["DeviceProperties"]["Add"] = {
        "PciRoot(0x0)/Pci(0x2,0x0)": {   # DVMT 固定 60MB（實測）
            "framebuffer-patch-enable": bytes.fromhex("01000000"),
            "framebuffer-stolenmem": bytes.fromhex("0000C003"),
            # 內建面板 EDID（367f:9001）只把 byte17 年份 2002→2020、checksum 0x2b→0x19，其餘原樣。
            # 年份 <2007 時 AppleBacklight 走舊式 non-linear 路徑：只發佈 linear-brightness-probe、
            # 沒有 linear-brightness → CoreDisplay 調亮度寫不到 bklt（docs/HANDOFF.md「亮度」）。
            "AAPL00,override-no-connect": bytes.fromhex(
                "00ffffffffffff00367f019001000000001e010380090f782f0000a057499b26"
                "10484f00000001010101010101010101010101010101c76c0038a14010606"
                "40c7400d88700000018000000fc004257380a202020202020202020000000fd"
                "003c3c7d7d1000000000000000000000000000000000000000000000000000000019"),
        },
        # 安裝期間先用輪詢，少依賴 GPIO 中斷一個環節；裝好後可拿掉試中斷模式（master 已支援 INT34C5）
        # I2C0 = 觸控板 SYNA3602，I2C1 = 觸控螢幕 GXTP7386（docs/hardware.md）
        # 2026-11-19：macOS 下輕點時游標跳、觸控螢幕偶爾沒反應；Fedora 正常且兩個都走 GPIO 中斷（intel-gpio 264/337）
        # → I2C0 試過拿掉 force-polling 改中斷（Interrupt Mode=GPIO、gpioPin 264 都對）：**更糟**——hidsniff 只收到開頭 0.27 s（40 筆、148 Hz）
        #   之後中斷不再來，游標幾乎不動。疑 VoodooGPIO TGL 把 ACPI Level/ActiveLow 當邊緣觸發、漏一次就卡死（未證實）。→ 改回輪詢。
        "PciRoot(0x0)/Pci(0x15,0x0)": {"force-polling": bytes.fromhex("01000000")},
        "PciRoot(0x0)/Pci(0x15,0x1)": {"force-polling": bytes.fromhex("01000000")},
        "PciRoot(0x0)/Pci(0x1f,0x3)": {  # ALC269VC，沒聲音依序試 7、8、13、22
            "layout-id": (6).to_bytes(4, "little"),
        },
    }
    if I2C0_GPIO_IRQ:
        del cfg["DeviceProperties"]["Add"]["PciRoot(0x0)/Pci(0x15,0x0)"]  # 觸控板改 GPIO 中斷（見 I2C0_GPIO_IRQ）
    if I2C1_GPIO_IRQ:
        assert I2C0_GPIO_IRQ, "I2C1_GPIO_IRQ needs the VoodooGPIO Kernel Patch added by I2C0_GPIO_IRQ"
        del cfg["DeviceProperties"]["Add"]["PciRoot(0x0)/Pci(0x15,0x1)"]  # 觸控螢幕改 GPIO 中斷（見 I2C1_GPIO_IRQ）
    cfg["DeviceProperties"]["Delete"] = {}

    # ---- Kernel ----
    cfg["Kernel"]["Add"] = [kext_entry(b, en, c) for _, b, en, c in KEXTS]
    cfg["Kernel"]["Block"] = []
    cfg["Kernel"]["Force"] = []
    cfg["Kernel"]["Patch"] = []
    if I2C0_GPIO_IRQ:
        # VoodooGPIOIntel::getInterruptType：xor edx,edx; test byte [rcx+rax*4],0xc; setne dl → mov edx,1; nop×4
        # （VoodooI2C 6be653a2 內附 VoodooGPIO 1.1，檔案偏移 0x4017，全檔唯一）
        cfg["Kernel"]["Patch"].append({
            "Arch": "x86_64", "Base": "", "Comment": "VoodooGPIO getInterruptType always Level (onb4 I2C0 GPIO IRQ)",
            "Count": 1, "Enabled": True,
            "Find": bytes.fromhex("488B496831D2F604810C0F95C2418916"),
            "Identifier": "org.coolstar.VoodooGPIO", "Limit": 0, "Mask": b"", "MaxKernel": "", "MinKernel": "",
            "Replace": bytes.fromhex("488B4968BA0100000090909090418916"), "ReplaceMask": b"", "Skip": 0,
        })
    if TS_CONTACT_ID_FIX:
        # VoodooI2CHID（6be653a2 CI 產物）handleDigitizerReport @0x30dd：movzx eax,[r15+0x112]; dec eax; cmp eax,esi; je +0x4b
        # → jmp +0x4b（檔案偏移 0x30d1 起 16 bytes，全檔唯一）
        cfg["Kernel"]["Patch"].append({
            "Arch": "x86_64", "Base": "", "Comment": "VoodooI2CHID: ignore contact-id wrapper reindex (onb4 GXTP7386 tracking ids)",
            "Count": 1, "Enabled": True,
            "Find": bytes.fromhex("410FB68712010000FFC839F0744B498B"),
            "Identifier": "com.alexandred.VoodooI2CHID", "Limit": 0, "Mask": b"", "MaxKernel": "", "MinKernel": "",
            "Replace": bytes.fromhex("410FB68712010000FFC839F0EB4B498B"), "ReplaceMask": b"", "Skip": 0,
        })
    # Tiger Lake 偽裝成 Ice Lake 0x706E5（4 台 Tiger Lake 參考 EFI 皆同，配 MacBookPro16,2）
    # 原本抄 XPS13Plus 的 Comet Lake 0xA0655，但那台是 Alder Lake；在這台會停在 EXITBS:START（2026-11-03）
    em = cfg["Kernel"]["Emulate"]
    em["Cpuid1Data"] = bytes.fromhex("E5060700000000000000000000000000")
    em["Cpuid1Mask"] = bytes.fromhex("FFFFFFFF000000000000000000000000")
    kq = cfg["Kernel"]["Quirks"]
    # 4 台 Tiger Lake 參考 EFI 都開 AppleXcpmExtraMsrs；ProvideCurrentCpuInfo 只有 1 台開（原本抄自 Alder Lake 的 XPS）
    for k in ("AppleXcpmCfgLock", "AppleXcpmExtraMsrs", "DisableIoMapper", "DisableLinkeditJettison",
              "PanicNoKextDump", "PowerTimeoutKernelPanic"):
        kq[k] = True
    kq["ProvideCurrentCpuInfo"] = False
    kq["XhciPortLimit"] = False

    # ---- Misc ----
    mb = cfg["Misc"]["Boot"]
    # 2026-11-19：選單鍵盤修好（見 UEFI.Input）、OpenCanopy 與 Fedora 項目 USB 實測 OK → OC 取代 GRUB 當開機選單
    # PickerAttributes 0x91 = 卷宗自訂圖示 0x1 + 指標控制 0x10 + flavour 圖示 0x80
    mb.update(PickerMode="External", PickerVariant=PICKER_THEME.replace("/", "\\"),
              PickerAttributes=0x91, ShowPicker=True, Timeout=20 if USB_VARIANT else 5, HideAuxiliary=True,
              PollAppleHotKeys=True)
    # 2026-11-12 休眠實驗：key 存 NVRAM（搭配 HibernationFixup），不用 RTC（非 Apple 韌體寫 RTC 可能觸發 CMOS checksum 重設）
    mb["HibernateMode"] = "NVRAM"
    md = cfg["Misc"]["Debug"]
    # 2026-11-10：關掉寫檔（0x40）與 AppleDebug（boot.efi log 也會寫檔）→ 寫 USB FAT 很慢、拖慢開機；要查 OpenCore 時改回 0x43/True
    md.update(AppleDebug=USB_VARIANT, ApplePanic=True, DisableWatchDog=True,
              # 2026-11-19：圖形選單上不印任何 log（原 0x03 會把 ERROR 蓋在畫面上）；要查 OC 用 USB 測試碟改 0x41（寫檔）
              Target=0x41 if USB_VARIANT else 0x00,
              # 2026-11-10：原本 0x80000042（ERROR+WARN+INFO）在 2560x1600 GOP 上逐行捲動要 ~7 分鐘（ACPI/kext 注入訊息）→ 只留 ERROR
              # USB 版 Target 0x41 不印螢幕、只寫檔 → 可用 INFO（0x80000042）
              DisplayLevel=0x80000042 if USB_VARIANT else 0x80000002, DisplayDelay=0)
    ms = cfg["Misc"]["Security"]
    # 只掃 NVMe/USB 上的 APFS/HFS+：ESP（EFI、NO NAME）與 exFAT 不列出 → 安裝程式成為唯一項目
    SCAN = 0x1 | 0x2 | 0x100 | 0x200 | 0x80000 | 0x200000   # = 0x280303
    ms.update(SecureBootModel="Disabled", Vault="Optional", ScanPolicy=SCAN, DmgLoading="Signed",
              AllowSetDefault=True, BlacklistAppleUpdate=True, ExposeSensitiveData=6)
    # Fedora：OC → 內建 ESP 的 shim → GRUB（GRUB 預設改回 Fedora、隱藏選單）。完整 device path，USB 上的 OC 也找得到。
    # 路徑來自 secrets/machine.json（Fedora 下 efibootmgr -v 的 Fedora 項目：NVMe EUI＋ESP PARTUUID）
    shim = machine().get("fedora_shim")
    cfg["Misc"]["Entries"] = [{
        "Arguments": "", "Auxiliary": False,
        "Comment": "Fedora via shim/GRUB on internal ESP" + ("" if shim else " (set your own device path, then enable)"),
        "Enabled": bool(shim), "Flavour": "Fedora:Linux", "Name": "Fedora",
        "Path": shim or FEDORA_SHIM_PLACEHOLDER,
        "TextMode": False}]
    cfg["Misc"]["Tools"] = [{
        "Arguments": "", "Auxiliary": True, "Comment": "OpenShell", "Enabled": True,
        "Flavour": "OpenShell:UEFIShell:Shell", "FullNvramAccess": False, "Name": "UEFI Shell",
        "Path": "OpenShell.efi", "RealPath": False, "TextMode": False}]

    # ---- NVRAM ----
    g = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
    nv = cfg["NVRAM"]["Add"][g]
    nv["boot-args"] = BOOT_ARGS
    nv["csr-active-config"] = bytes.fromhex("03080000")  # WhateverXe 要求 0x803
    nv["prev-lang:kbd"] = b"en-US:0"
    # Intel BT on Monterey+（BrcmPatchRAM README）：避免 bluetoothd 把內建控制器當失敗的外接 dongle。
    # Add+Delete 讓每次開機都覆寫（IntelBluetoothFirmware #505）。
    nv["bluetoothExternalDongleFailed"] = b"\x00"
    nv["bluetoothInternalControllerInfo"] = bytes(14)
    for k in ("boot-args", "csr-active-config", "prev-lang:kbd",
              "bluetoothExternalDongleFailed", "bluetoothInternalControllerInfo"):
        if k not in cfg["NVRAM"]["Delete"][g]:
            cfg["NVRAM"]["Delete"][g].append(k)
    cfg["NVRAM"]["WriteFlash"] = True

    # ---- PlatformInfo ----
    gi = cfg["PlatformInfo"]["Generic"]
    if PUBLIC:
        # 序號／MLB／UUID／ROM 保留 Sample.plist 的佔位值：使用者要自己用 GenSMBIOS／macserial 產生
        gi.update(SystemProductName=SMBIOS_MODEL)
    else:
        s = smbios()
        gi.update(SystemProductName=s["model"], SystemSerialNumber=s["serial"], MLB=s["mlb"],
                  SystemUUID=s["uuid"], ROM=bytes.fromhex(s["rom"]))
    cfg["PlatformInfo"]["UpdateSMBIOSMode"] = "Create"

    # ---- UEFI ----
    cfg["UEFI"]["Drivers"] = [{"Arguments": "", "Comment": d, "Enabled": True,
                               "HideVerbose": False, "LoadEarly": False, "Path": d} for d in DRIVERS]
    # 2026-11-19 實測：KeySupport=false 時內建選單完全沒有按鍵來源（沒裝 OpenUsbKbDxe 等驅動就只能靠它）；
    # KeySupport=true（Auto，AIK 抓到 ConSplitter）方向鍵/Enter 正常。
    # 但韌體一開始會吐一筆非法按鍵 → 倒數立刻被取消、Timeout 後停在選單（11-03 的「Timeout 後停住」）；
    # KeyFiltering=true 丟掉非法按鍵後會照 Timeout 自動開機（build/logs/picker1-20261119/）。
    cfg["UEFI"]["Input"].update(KeySupport=True, KeySupportMode="Auto", KeyFiltering=True)
    cfg["UEFI"]["Output"]["UIScale"] = 2   # 2560x1600 HiDPI（OpenCanopy 用 2x 圖）
    uq = cfg["UEFI"]["Quirks"]
    uq["ReleaseUsbOwnership"] = True
    uq["RequestBootVarRouting"] = True
    cfg["UEFI"]["ReservedMemory"] = []

    with open(OUT / "OC/config.plist", "wb") as f:
        plistlib.dump(cfg, f, sort_keys=False)

    r = subprocess.run([str(OC / "Utilities/ocvalidate/ocvalidate"), str(OUT / "OC/config.plist")],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    print("EFI ->", OUT)


if __name__ == "__main__":
    main()
