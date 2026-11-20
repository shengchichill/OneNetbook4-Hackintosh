#!/bin/bash
# Fedora（GNOME/Wayland）上反覆「關螢幕 → 開螢幕」，對照 macOS display sleep 失敗（面板再上電後 AUX 不回）。
# 用法：sudo bash onb4-linux-dpms.sh [次數=10] [關閉秒數=10]  → ~/onb4-dpms-<時間>/
# 關/開螢幕走 Mutter 的 org.gnome.Mutter.DisplayConfig PowerSaveMode（3=off、0=on），跟登入使用者的 session bus 講話。
# 每輪：開回來後等 5 秒，讀 eDP 的 DPCD 0x000/0x100/0x200/0x600（AUX 活著嗎）、收集新增的 dmesg（i915 訊息）。
# 第 1 輪另外在「關閉中」與「開回後」各跑一次 onb4-linux-regdump.sh。只讀暫存器、不寫。
set -u
n=${1:-10}; off=${2:-10}
user=${SUDO_USER:?run with sudo}; uid=$(id -u "$user")
here=$(cd "$(dirname "$0")" && pwd)
out=/home/$user/onb4-dpms-$(date +%H%M%S); mkdir -p "$out"
bus="unix:path=/run/user/$uid/bus"
psm() { sudo -u "$user" DBUS_SESSION_BUS_ADDRESS="$bus" gdbus call --session --dest org.gnome.Mutter.DisplayConfig \
  --object-path /org/gnome/Mutter/DisplayConfig --method org.freedesktop.DBus.Properties.Set \
  org.gnome.Mutter.DisplayConfig PowerSaveMode "<int32 $1>" >/dev/null; }
edp_aux() { for a in /dev/drm_dp_aux*; do
  case "$(cat /sys/class/drm_dp_aux_dev/$(basename "$a")/name 2>/dev/null)" in *DDI\ A*|*eDP*) echo "$a"; return;; esac; done; }
dpcd() { local a=$1; for r in 0x000:4 0x100:2 0x200:8 0x600:1; do
  printf '%s=' "${r%%:*}"; dd if="$a" bs=1 skip=$((${r%%:*})) count=${r##*:} 2>/dev/null | od -An -tx1 | tr -d '\n'
  [ "${PIPESTATUS[0]}" = 0 ] || printf ' (讀取失敗)'; printf '  '; done; echo; }
aux=$(edp_aux); echo "eDP AUX: ${aux:-找不到}  名稱: $(cat /sys/class/drm_dp_aux_dev/$(basename "${aux:-x}")/name 2>/dev/null)" | tee "$out/summary.txt"
dmesg --time-format iso > "$out/dmesg-before.txt"; last=$(wc -l < "$out/dmesg-before.txt")
for i in $(seq "$n"); do
  echo "== 第 $i 輪 $(date +%T)" | tee -a "$out/summary.txt"
  psm 3; sleep "$off"
  [ "$i" = 1 ] && bash "$here/onb4-linux-regdump.sh" "dpms-off" >/dev/null && mv "/home/$user/onb4-regdump-dpms-off.txt" "$out/"
  psm 0; sleep 5
  [ -n "$aux" ] && { printf '  DPCD: '; dpcd "$aux"; } | tee -a "$out/summary.txt"
  [ "$i" = 1 ] && bash "$here/onb4-linux-regdump.sh" "dpms-on" >/dev/null && mv "/home/$user/onb4-regdump-dpms-on.txt" "$out/"
  dmesg --time-format iso > "$out/dmesg-now.txt"; total=$(wc -l < "$out/dmesg-now.txt")
  tail -n +$((last + 1)) "$out/dmesg-now.txt" | grep -iE 'i915|drm|edp|link|aux|train' | sed 's/^/  dmesg: /' | tee -a "$out/summary.txt"
  last=$total
done
chown -R "$user" "$out"; echo "完成 → $out"
