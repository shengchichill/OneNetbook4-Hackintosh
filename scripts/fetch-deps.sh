#!/usr/bin/env bash
# 下載 OpenCore 與 kext 到 build/deps（版本固定，升級時改這裡）
set -euo pipefail
cd "$(dirname "$0")/.."
D=build/deps; mkdir -p "$D"

# repo|tag|asset pattern
DEPS=(
  "acidanthera/OpenCorePkg|1.0.8|OpenCore-1.0.8-RELEASE.zip"
  "acidanthera/OpenCorePkg|1.0.8|OpenCore-1.0.8-DEBUG.zip"
  "acidanthera/Lilu|1.7.2|Lilu-1.7.2-RELEASE.zip"
  "acidanthera/VirtualSMC|1.3.8|VirtualSMC-1.3.8-RELEASE.zip"
  "acidanthera/AppleALC|1.9.8|AppleALC-1.9.8-RELEASE.zip"
  "acidanthera/HibernationFixup|1.5.4|HibernationFixup-1.5.4-RELEASE.zip"
  "acidanthera/NVMeFix|1.1.3|NVMeFix-1.1.3-RELEASE.zip"
  "acidanthera/RestrictEvents|1.1.6|RestrictEvents-1.1.6-RELEASE.zip"
  "acidanthera/VoodooPS2|2.3.7|VoodooPS2Controller-2.3.7-RELEASE.zip"
  "acidanthera/BrcmPatchRAM|2.7.2|BrcmPatchRAM-2.7.2-RELEASE.zip"
  "VoodooI2C/VoodooI2C|v2.9.1|VoodooI2C-2.9.1-RELEASE.zip"
  "1Revenger1/ECEnabler|1.0.6|ECEnabler-1.0.6-RELEASE.zip"
  "OpenIntelWireless/itlwm|v2.3.0|itlwm_v2.3.0_stable.kext.zip"
  "OpenIntelWireless/IntelBluetoothFirmware|v2.4.0|IntelBluetooth-v2.4.0.zip"
  "USBToolBox/kext|1.2.0|USBToolBox-1.2.0-RELEASE.zip"
  "b00t0x/WhateverXe|0.7.0|WhateverXe-0.7.0-RELEASE.zip"
  "b00t0x/WhateverXe-Graphics|v0.4.0|WhateverXe-Graphics-0.4.0.pkg"
  "OpenIntelWireless/HeliPort|*|HeliPort.dmg"
)

for e in "${DEPS[@]}"; do
  IFS='|' read -r repo tag asset <<<"$e"
  [ -f "$D/$asset" ] && { echo "have  $asset"; continue; }
  echo "fetch $asset"
  if [ "$tag" = "*" ]; then gh release download -R "$repo" -p "$asset" -D "$D"
  else gh release download "$tag" -R "$repo" -p "$asset" -D "$D"; fi
done

# AMFIPass Mod 放在 WhateverXe-Graphics repo 的 extras/
A=AMFIPass-v1.4.1-Mod-RELEASE.zip
[ -f "$D/$A" ] || gh api "repos/b00t0x/WhateverXe-Graphics/contents/extras/$A" \
  -H "Accept: application/vnd.github.raw" > "$D/$A"

# VoodooI2C：2.9.1 release 不支援 Tiger Lake，用 master 6be653a2（2026-10-25）的 CI 產物。
# GitHub Actions artifact 約 90 天後過期；過期前已下載的 zip 留在 build/deps/，或改用新的正式版。
V=VoodooI2C-6be653a2
[ -f "$D/$V/Release/VoodooI2C-2.9.1-RELEASE.zip" ] || \
  gh run download 40157687159 -R VoodooI2C/VoodooI2C -n "$V" -D "$D/$V"

# 解壓
# 只重建 zip 對應的資料夾：build/extract 裡還有本地編的 WEX（WhateverXe-0.7.0-onb4*），不可整個刪。
X=build/extract; mkdir -p "$X"
for z in "$D"/*.zip; do n=$(basename "$z" .zip); rm -rf "${X:?}/$n"; mkdir -p "$X/$n"; unzip -qo "$z" -d "$X/$n"; done
rm -rf "${X:?}/$V"; mkdir -p "$X/$V"; unzip -qo "$D/$V/Release/VoodooI2C-2.9.1-RELEASE.zip" -d "$X/$V"
# 手動項目（build-efi.py 需要，這個腳本抓不到）：
#   1. build/extract/WhateverXe-0.7.0-onb4quiet26-RELEASE/WhateverXe.kext
#      = b00t0x/WhateverXe d0b7fb6（patches/WhateverXe-0.7.0-onb4.base.txt）＋ patches/WhateverXe-0.7.0-onb4.patch，Xcode RELEASE 編譯
#   2. build/extract/IntelBluetooth-v2.5.1/{IntelBluetoothFirmware,IntelBTPatcher}.kext
#      = lshbluesky 的 IntelBluetoothFirmware fork 2.5.1（Tahoe 支援；上游 v2.4.0 在 Tahoe 不能用）
missing=0
for k in "$X/WhateverXe-0.7.0-onb4quiet26-RELEASE/WhateverXe.kext" \
         "$X/IntelBluetooth-v2.5.1/IntelBluetoothFirmware.kext" "$X/IntelBluetooth-v2.5.1/IntelBTPatcher.kext"; do
  [ -d "$k" ] || { echo "MISSING (manual): $k"; missing=1; }
done
[ "$missing" = 0 ] || echo "see the comments above / README for how to get the manual items"
echo "done -> $X"
