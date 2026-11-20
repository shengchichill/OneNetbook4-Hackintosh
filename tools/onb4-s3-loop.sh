#!/bin/bash
# S3 循環 + 每次喚醒後 GPU 檢查：驗證「同次開機 S3 次數越多 → GPU（WindowServer RCS）越容易 hang」。
# 用法（OneNetbook 上，需要 root 才能排 RTC 喚醒）：
#   sudo -b bash ~/workspace/onb4-hackintosh/tools/onb4-s3-loop.sh <循環次數> <壓測秒數> [喚醒延遲秒]
# 每次：pmset relative wake → pmset sleepnow → 等 pmset log 出現新的喚醒 → caffeinate -u 點亮 →
#   存 ioreg → gpucheck（60 s 逾時）→ gpucheck <壓測秒數>（逾時 = 秒數+60）→ 檢查新的 GPURestart / gpuRestart 報告。
# 出現 GPU 重置、gpucheck 逾時或失敗就停，結果寫在 ~$ONB4_USER/s3loop-<時間>/log.txt（每輪 ioreg 也在該目錄）。
set -u
N=${1:-8}; STRESS=${2:-60}; WAKE=${3:-45}
U=${ONB4_USER:?set ONB4_USER to your macOS user name}; H=/Users/$U
GC=$H/workspace/onb4-hackintosh/tools/gpucheck/gpucheck
OUT=$H/s3loop-$(date +%Y%m%d-%H%M%S); mkdir -p "$OUT"; chown $U "$OUT"
LOG=$OUT/log.txt
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
wakes() { pmset -g log | grep -cE '(Wake|DarkWake) from (Normal|Deep|Standby)'; }
# log show --start 會混進時鐘跳動前的舊紀錄 → 再用時間戳記字串比較濾掉
restarts_since() { /usr/bin/log show --start "$1" --style compact --predicate 'eventMessage CONTAINS "GPURestartSignaled"' 2>/dev/null | grep 'GPURestartSignaled stampIdx' | awk -v s="$1" 'substr($0,1,19)>=s' | wc -l | tr -d ' '; }
# 11-18 起 S3 期間 RTC 會跳快整數小時（+122 h、+150 h）而錯過 RTC 喚醒 → 每輪量偏移並校正。
# clkoff：等網路最多 ~60 s，印 sntp 偏移秒數（量不到印 ?）；clkfix：偏移 >2 s 才 sntp -sS
clkoff() { local o; for ((k=0;k<12;k++)); do o=$(sntp -t 3 time.apple.com 2>/dev/null | awk '$2=="+/-"{print $1; exit}'); [ -n "$o" ] && { echo "$o"; return; }; sleep 5; done; echo '?'; }
clkfix() { local o=$1; [ "$o" = '?' ] && return; awk -v o="$o" 'BEGIN{exit !(o>2||o<-2)}' && sntp -sS time.apple.com >/dev/null 2>&1; }
reports() { ls /Library/Logs/DiagnosticReports 2>/dev/null | grep -c 'gpuRestart$'; }
# 以 $U 身分、有逾時地跑 gpucheck；回傳 0=PASS 1=FAIL 2=逾時
gpu() { # $1 逾時秒 $2.. 參數
  local t=$1; shift
  sudo -u $U "$GC" "$@" > "$OUT/gc.tmp" 2>&1 & local p=$!
  for ((i=0;i<t;i++)); do kill -0 $p 2>/dev/null || break; sleep 1; done
  if kill -0 $p 2>/dev/null; then kill -9 $p; return 2; fi
  wait $p; grep -q 'RESULT: PASS\|errors=0' "$OUT/gc.tmp" && return 0 || return 1
}
say "start N=$N stress=${STRESS}s wake=${WAKE}s boot=$(sysctl -n kern.boottime | sed 's/.*} //') reports=$(reports)"
R0=$(reports); T0=$(date +%Y-%m-%d-%H%M%S)
# 只數檔名時間戳晚於迴圈開始的報告：macOS 會清舊報告、也會整批改寫舊報告的 mtime（11-13 11:06:44 第 2 輪因此 newReports=-5 誤判）
newreports() { ls /Library/Logs/DiagnosticReports 2>/dev/null | sed -n 's/^Kernel_\([0-9-]\{17\}\)_.*gpuRestart$/\1/p' | awk -v t="$T0" '$1>t' | wc -l | tr -d ' '; }
for ((c=1;c<=N;c++)); do
  o=$(clkoff); clkfix "$o"; [ "$o" != '?' ] && awk -v o="$o" 'BEGIN{exit !(o>2||o<-2)}' && say "cycle $c: 睡前時鐘偏移 ${o}s，已校正"
  # 11-18 發現：壞的是 RTC 硬體（醒著時日／時被改），系統時鐘是對的 → 上面量不到。
  # RTC 錯了 AppleRTC 就不排 alarm（沒有 "RTC: Alarm" 紀錄）→ 不會醒。睡前一律用 settimeofday 重寫 RTC。
  tsn=$(date '+%Y-%m-%d %H:%M:%S'); sntp -sS time.apple.com >/dev/null 2>&1
  start=$(date '+%Y-%m-%d %H:%M:%S'); w0=$(wakes)
  # 遠端 tty 還開著時 powerd（ttyskeepawake）會把 sleepnow 變成 DarkWake、不會真的睡（16:11 那次就卡在這）。
  for ((i=0;i<30;i++)); do [ -z "$(who | grep "(" )" ] && break; sleep 2; done
  if [ -n "$(who | grep "(" )" ]; then say "cycle $c: 還有遠端 tty 登入（$(who | grep "("  | awk '{print $2}' | xargs)），會擋住 S3，停止"; exit 1; fi
  for ((try=1;try<=3;try++)); do
    t0=$(date '+%Y-%m-%d %H:%M:%S')
    pmset relative wake "$WAKE" >/dev/null 2>&1 || { say "cycle $c: pmset relative wake 失敗（需要 root）"; exit 1; }
    say "cycle $c: sleep$([ $try -gt 1 ] && echo " (retry $try)")"
    pmset sleepnow >/dev/null
    aborted=0
    for ((i=0;i<300;i++)); do sleep 2; [ "$(wakes)" -gt "$w0" ] && break
      [ $i -eq 15 ] || continue
      # 上限：RTC 跳快留下的未來日期紀錄（11-23 的 DarkWake）會被誤判（11-19 第 10 輪）
      since=$(pmset -g log | awk -v s="$t0" -v e="$(date -v+10M '+%Y-%m-%d %H:%M:%S')" '$1" "$2>=s && $1" "$2<=e')
      if echo "$since" | grep -q "Entering DarkWake state due to 'Software Sleep"; then
        say "cycle $c: sleepnow 變成 DarkWake（沒進 S3），停止"; caffeinate -u -t 5; exit 1; fi
      # 17:03 那次：sleepnow 同一秒觸控板有輸入 → 螢幕 1 s 後又亮、沒進 S3、也沒有 DarkWake 紀錄
      if echo "$since" | grep -q "Display is turned on"; then aborted=1; break; fi
    done
    [ $aborted -eq 0 ] && break
    say "cycle $c: 睡眠被打斷（螢幕又亮、沒有喚醒紀錄；$(echo "$since" | grep -o 'UserIsActive "[^"]*product:[^ ]*' | tail -1)），第 $try 次"
    [ $try -eq 3 ] && { say "cycle $c: 連續 3 次睡不著，停止"; exit 1; }
    sleep 10
  done
  if [ "$(wakes)" -le "$w0" ]; then say "cycle $c: 600 s 內沒偵測到喚醒，停止"; exit 1; fi
  sleep 5; caffeinate -u -t 5; sleep 10
  # sntp 偏移 = 正確時間 − 本機時間；負值 = 本機跳快。先校正，後面 restarts_since 的時間比較才對
  clk=$(clkoff); clkfix "$clk"
  # AppleRTC 紀錄：睡前有沒有排 alarm、RTC 讀值與系統時間的差（秒；0 附近 = RTC 正常）
  rl=$(/usr/bin/log show --start "$t0" --style compact --predicate 'eventMessage BEGINSWITH "RTC:"' 2>/dev/null | awk -v s="$t0" 'substr($0,1,19)>=s')
  rtcset=$(/usr/bin/log show --start "$tsn" --style compact --predicate 'eventMessage BEGINSWITH "RTC: setGMTTimeOfDay"' 2>/dev/null | awk -v s="$tsn" 'substr($0,1,19)>=s' | grep -c setGMT)  # 確認 sntp -sS 有真的寫 RTC
  alarm=$(echo "$rl" | grep -q 'RTC: Alarm' && echo yes || echo NO)
  rtcskew=$(echo "$rl" | grep 'getGMTTimeOfDay' | awk '{print $1" "substr($2,1,8), $NF}' | while read d t v; do echo $((v - $(date -j -f '%Y-%m-%d %H:%M:%S' "$d $t" +%s))); done | awk '{a=$1<0?-$1:$1; if(a>m){m=a;x=$1}} END{print x+0}')
  how=$(pmset -g log | grep -E '(Wake|DarkWake) from' | tail -1 | cut -c27-110)
  ioreg -p IOService -d 1 -l -w0 > "$OUT/cycle$c-ioreg.txt"
  lt=$(grep -oE '"ONB4LTRetry" = <[0-9a-f]*>' "$OUT/cycle$c-ioreg.txt" | sed 's/.*<//; s/>//')
  sh=$(grep -oE '"ONB4SyncTrace" = <[0-9a-f]{16}' "$OUT/cycle$c-ioreg.txt" | sed 's/.*<//'); sb=${sh:8:8}
  sync=$([ -n "$sb" ] && echo $((16#${sb:6:2}${sb:4:2}${sb:2:2}${sb:0:2})) || echo '?') # ㉑ generateSync 累計呼叫數
  ws=$(pgrep -x WindowServer >/dev/null && echo up || echo DOWN)
  gpu 60; g1=$?
  gpu $((STRESS+60)) "$STRESS"; g2=$?
  stress=$(grep -E '^stress' "$OUT/gc.tmp" | cut -c1-90)
  rs=$(restarts_since "$start"); rn=$(newreports)
  eh=$(grep -oE '"ONB4ElsqWait" = <[0-9a-f]{40}' "$OUT/cycle$c-ioreg.txt" | sed 's/.*<//')  # ㉔ waits(第4個u32)/timeouts(第5個)
  le(){ local x=${eh:$1:8}; [ -n "$x" ] && echo $((16#${x:6:2}${x:4:2}${x:2:2}${x:0:2})) || echo '?'; }
  elsq="$(le 24)/$(le 32)"
  eh=$(grep -oE '"ONB4SchedTrace" = <[0-9a-f]{24}' "$OUT/cycle$c-ioreg.txt" | sed 's/.*<//')  # ㉕ frozen(第2個u32)/事件總數(第3個)
  sched="$(le 8)/$(le 16)"
  say "cycle $c: woke [$how] clk=${clk}s alarm=$alarm rtcset=$rtcset rtcskew=${rtcskew}s WS=$ws LTRetry=$lt sync=$sync elsq=$elsq sched=$sched gpucheck=$g1 stress=$g2 ($stress) GPURestartSignaled=$rs newReports=$rn"
  if [ "$g1" != 0 ] || [ "$g2" != 0 ] || [ "$rs" != 0 ] || [ "$rn" != 0 ]; then ioreg -p IOService -d 1 -l -w0 > "$OUT/hang$c-ioreg.txt"; say "cycle $c: GPU 異常，停止（hang 後 ioreg：hang$c-ioreg.txt，看 tools/onb4-sched.py）"; exit 2; fi
done
say "done: $N cycles OK"
