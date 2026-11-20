#!/bin/bash
# 日常使用時的 hang 自動存證（11-19）：hang 後機器常卡死、只能長按重開，㉕ 凍結的紀錄只在記憶體 → 偵測到就馬上存檔。
# 由 LaunchDaemon com.onb4.hangcapture 以 root 執行；輸出在 /Users/$ONB4_USER/hang-captures/（ONB4_USER 由 LaunchDaemon plist 的 EnvironmentVariables 設定）。
# 觸發：kernel log 出現 "GPURestartSignaled"（WEX hang 偵測後、Apple 重置 GPU 時）。
# 每次觸發：立刻存 ioreg（含 ONB4SchedTrace／TGLSubmitHistory），5 s 後再存一份，並 sync；同一分鐘內只觸發一次。
U=${ONB4_USER:?set ONB4_USER}; OUT=/Users/$U/hang-captures
mkdir -p "$OUT"; chown "$U" "$OUT"
last=""
/usr/bin/log stream --style compact --predicate 'eventMessage CONTAINS "GPURestartSignaled"' 2>/dev/null |
while IFS= read -r line; do
  # log stream 開頭會印 "Filtering the log data using ... GPURestartSignaled ..." → 只認真正的事件行（同 onb4-s3-loop.sh）
  case "$line" in *"GPURestartSignaled stampIdx"*) ;; *) continue ;; esac
  ts=$(date +%Y%m%d-%H%M%S); [ "${ts:0:13}" = "$last" ] && continue; last=${ts:0:13}
  ioreg -p IOService -d 1 -l -w0 > "$OUT/hang-$ts-ioreg.txt"; sync
  echo "$line" > "$OUT/hang-$ts-trigger.txt"
  sleep 5
  ioreg -p IOService -d 1 -l -w0 > "$OUT/hang-$ts-ioreg-5s.txt"; sync
  chown "$U" "$OUT"/hang-"$ts"-*
done
