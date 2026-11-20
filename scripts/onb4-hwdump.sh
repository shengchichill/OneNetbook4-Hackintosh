#!/usr/bin/env bash
# OneNetbook 4 硬體資訊收集（給 Hackintosh EFI / SSDT 製作用）
# 用法：sudo bash onb4-hwdump.sh   → 產生 ~/onb4-hwdump-<日期>.tar.gz
set -u
[ "$(id -u)" -eq 0 ] || { echo "請用 sudo 執行"; exit 1; }

dnf install -y acpica-tools dmidecode pciutils usbutils i2c-tools edid-decode >/dev/null 2>&1 || true

OUT="/root/onb4-hwdump-$(date +%Y%m%d-%H%M)"
mkdir -p "$OUT/acpi"
cd "$OUT"

run() { echo "### $*" >> "$2.txt" 2>/dev/null; }
cap() { local f="$1"; shift; { echo "### $*"; eval "$@"; } > "$f.txt" 2>&1; }

cap system    "uname -a; cat /etc/os-release; dmidecode -t system -t bios -t baseboard -t processor -t memory"
cap pci       "lspci -nnk; echo; lspci -vvv -nn"
cap usb       "lsusb; echo; lsusb -t; echo; lsusb -v 2>/dev/null"
cap cpu       "lscpu; grep -m1 microcode /proc/cpuinfo"
cap input     "cat /proc/bus/input/devices"
cap i2c       "for d in /sys/bus/i2c/devices/*; do echo \"== \$d\"; cat \$d/name \$d/modalias 2>/dev/null; readlink -f \$d/firmware_node 2>/dev/null; done; echo; ls -l /sys/bus/i2c/drivers/*/"
cap hid       "for d in /sys/bus/hid/devices/*; do echo \"== \$d\"; cat \$d/uevent; done"
cap acpi_ids  "for d in /sys/bus/acpi/devices/*; do printf '%s ' \"\$(basename \$d)\"; cat \$d/path 2>/dev/null || echo; done"
cap audio     "aplay -l; cat /proc/asound/cards; for c in /proc/asound/card*/codec#*; do echo \"== \$c\"; head -40 \$c; done"
cap storage   "lsblk -o NAME,MODEL,SIZE,TRAN,TYPE; nvme list 2>/dev/null"
cap net       "ip link; iw dev 2>/dev/null; rfkill list"
cap gpu       "cat /sys/kernel/debug/dri/0/i915_capabilities 2>/dev/null; cat /sys/kernel/debug/dri/0/i915_gpu_info 2>/dev/null | head -80; cat /sys/kernel/debug/dri/0/i915_display_info 2>/dev/null"
cap edid      "for e in /sys/class/drm/card*-*/edid; do echo \"== \$e\"; edid-decode \$e 2>/dev/null || xxd \$e; done"
cap backlight "ls -l /sys/class/backlight/; for b in /sys/class/backlight/*; do echo \$b; cat \$b/max_brightness \$b/brightness; done"
cap power     "cat /sys/power/mem_sleep; cat /sys/power/state; ls /sys/class/power_supply/; for p in /sys/class/power_supply/*; do echo \"== \$p\"; cat \$p/uevent; done"
cap sensors   "ls /sys/bus/iio/devices/ 2>/dev/null; for d in /sys/bus/iio/devices/*; do echo \"== \$d\"; cat \$d/name; done"
cap dmesg     "dmesg"
cap efi       "ls /sys/firmware/efi/efivars | head -200; mokutil --sb-state 2>/dev/null"

# 完整 ACPI 表（DSDT/SSDT），做 SSDT 熱修補一定要
( cd acpi && acpidump -b && for f in *.dat; do iasl -d "$f" >/dev/null 2>&1; done )

cd /root
TAR="onb4-hwdump-$(date +%Y%m%d).tar.gz"
tar czf "$TAR" "$(basename "$OUT")"
cp "$TAR" "/home/${SUDO_USER:-root}/" 2>/dev/null && chown "${SUDO_USER:-root}" "/home/${SUDO_USER:-root}/$TAR"
echo "完成：/home/${SUDO_USER:-root}/$TAR"
