#!/bin/bash
# S3 喚醒黑屏測試用：睡前在 OneNetbook（macOS）背景執行，喚醒後自動拍 ioreg。
#   nohup bash ~/workspace/onb4-hackintosh/tools/onb4-wake-capture.sh >/dev/null 2>&1 &
#   sleep 2; pmset sleepnow
# 每 5 秒看一次牆鐘；兩次之間跳超過 12 秒 = 剛從睡眠醒來（睡眠中 sleep 不計時；30 秒門檻曾漏掉只睡 25 秒的喚醒）。
# 醒來後第 0/20/60/150 秒把 ioreg 寫到 ~/wake-ioreg-<秒>.txt，時間記在 ~/wake-marker.txt，每次都 sync。
# ioreg 在背景跑（卡住也不擋心跳）；醒後每 2 秒寫一行心跳到 ~/wake-marker.txt，用來判斷系統是何時當掉的。
# 開始時先拍一份睡前的 ~/wake-ioreg-pre.txt。只處理第一次喚醒，最多等 1 小時。
out=$HOME
mark=$out/wake-marker.txt
snap() { /usr/sbin/ioreg -p IOService -d 1 -l -w0 > "$out/wake-ioreg-$1.txt"; echo "$(date +%T) $1" >> "$mark"; sync; }
hb() { local t0=$1 n=$2; for _ in $(seq "$n"); do echo "$(date +%T) hb +$(( $(date +%s) - t0 ))s" >> "$mark"; sync; sleep 2; done; }
echo "$(date +%T) start pid=$$" > "$mark"
snap pre
prev=$(date +%s)
for _ in $(seq 720); do
  sleep 5
  now=$(date +%s)
  if (( now - prev > 12 )); then
    echo "$(date +%T) wake detected gap=$((now - prev))s" >> "$mark"; sync
    t0=$now
    hb "$t0" 80 &
    snap 0 &
    sleep 15; snap 20 &
    sleep 40; snap 60 &
    sleep 90; snap 150
    wait; exit 0
  fi
  prev=$now
done
echo "$(date +%T) no wake within 1h" >> "$mark"
