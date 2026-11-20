#!/bin/bash
# Fedora（i915）上 dump eDP 相關暫存器與面板 DPCD，當作「正確開機／喚醒」的參考值，跟 macOS ONB4WakeTrace 比對。
# 需要 root 與 igt-gpu-tools（intel_reg）。用法：sudo bash onb4-linux-regdump.sh <標籤>  → ~/onb4-regdump-<標籤>.txt
# 只讀：intel_reg read 與 /dev/drm_dp_aux* 讀取，不寫任何東西。
set -u
tag=${1:-now}
out=/home/${SUDO_USER:?run with sudo}/onb4-regdump-$tag.txt
{
echo "# $(date '+%F %T') tag=$tag kernel=$(uname -r)"
r() { for a in "$@"; do intel_reg read "$a" 2>&1 | sed 's/^/  /'; done; }
echo "## 與 macOS trace 同一批"
r 0xC4000 0xC4004 0xC400C 0xC4030 0xC4034 0xC4038 0xC7200 0xC7204 0xC7208 0xC720C \
  0x45400 0x45404 0x45444 0x45504 0x46000 0x164280 0x64000 0x60400 0x60540 0x60544 \
  0x162014 0x162100 0x16210C 0x64C00 0x45454 0x162028 0x162804 \
  0x162888 0x162890 0x162894 0x16289C 0x162988 0x162990 0x162994 0x16299C 0x162120 \
  0x1628A0 0x1629A0 0x162904 0x162AA0
echo "## DPLL（DPLL0/1_ENABLE、TGL_DPLL0/1_CFGCR0/1）"
r 0x46010 0x46014 0x46020 0x164284 0x164288 0x16428C 0x164290
echo "## TRANS/PIPE A（timing、DATA_M/N、PIPECONF）"
r 0x60000 0x60004 0x60008 0x6000C 0x60010 0x60014 0x6001C 0x60030 0x60034 0x60040 0x60044 0x70008 0x6F000 0x6F004 0x6F008 0x6F00C 0x6F010 0x6F014 0x6F01C 0x6F030 0x6F034 0x6F040 0x6F044 0x7F008
echo "## PHY A 整段：CL/COMP 0x162000-0x16217C"
intel_reg read 0x162000 --count 96 2>&1 | sed 's/^/  /'
for ln in 0 1 2 3; do
  b=$((0x162800 + ln * 0x100))
  echo "## PHY A LN$ln PCS/TX $(printf 0x%x $b)-$(printf 0x%x $((b+0xFC)))"
  intel_reg read $(printf 0x%x $b) --count 64 2>&1 | sed 's/^/  /'
done
echo "## 與 WEX ⑫ ONB4PhyDump 同範圍（PHY 以外）"
for range in 0x164200:64 0x46000:8 0x46010:8 0x60000:32 0x60400:4 0x60500:24 0x64000:4 0x64C00:4 0x45400:8 0x45440:8 0x45500:4 0xC7200:4 0xC4000:16; do
  intel_reg read ${range%%:*} --count ${range##*:} 2>&1 | sed 's/^/  /'
done
echo "## DPCD（eDP 所在的 AUX）"
for aux in /dev/drm_dp_aux*; do
  name=$(cat /sys/class/drm_dp_aux_dev/$(basename "$aux")/name 2>/dev/null)
  echo "### $aux $name"
  for range in 0x000:16 0x100:16 0x200:8 0x600:1 0x700:16; do
    off=$((${range%%:*})); len=${range##*:}
    printf '  %#05x: ' $off
    dd if="$aux" bs=1 skip=$off count=$len 2>/dev/null | od -An -tx1 | tr -s ' \n' ' '
    echo
  done
done
} > "$out" 2>&1
chown "${SUDO_USER:?run with sudo}" "$out"
echo "wrote $out ($(wc -l < "$out") lines)"
