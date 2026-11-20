#!/usr/bin/env python3
"""解析 WEX ㉔ 的 ONB4ElsqWait（送 ELSP 前等 EXECLIST_STATUS bit30 的統計）。
用法：
  ssh user@<IP> 'ioreg -p IOService -d 1 -l -w0' > x.txt
  python3 tools/onb4-elsq.py x.txt [y.txt ...]
看點：waits 是否 >0（bit30 在送出當下真的會出現）、是否集中在喚醒後、timeouts 是否為 0。
"""
import re
import struct
import sys


def show(path):
    text = open(path, errors="replace").read()
    m = re.search(r'"ONB4ElsqWait" = <([0-9a-fA-F]*)>', text)
    if not m:
        print(f"{path}: 找不到 ONB4ElsqWait（WEX ㉔ 沒載入？）")
        return
    raw = bytes.fromhex(m.group(1))
    h = struct.unpack_from("<12I", raw)
    ver, nowait, calls, waits, timeouts, max_us, total_us, bad, wake_now, last_wake, waits_this, ringinfo = h
    ring_n, nxt = ringinfo & 0xFFFF, ringinfo >> 16
    print(f"== {path}  ver={ver} {'【-onb4noelsqwait：只記錄不等】' if nowait else '等待啟用'}")
    print(f"  RCS 送出 {calls} 次；送出當下 bit30=1：{waits} 次（逾時 {timeouts}）；最長 {max_us} µs、合計 {total_us} µs；讀到 0xFFFFFFFF {bad} 次")
    print(f"  目前 wakeCount={wake_now}；最後一次 bit30 事件在 wakeCount={last_wake}（該次喚醒共 {waits_this} 次）")
    recs = []
    for i in range(ring_n):
        e = struct.unpack_from("<8I", raw, 48 + i * 32)
        if e[1] == 0 and e[5] == 0:
            continue
        recs.append(((i - nxt) % ring_n, e))
    if not recs:
        print("  （沒有 bit30 事件）")
        return
    print("  最近的 bit30 事件（舊→新）：")
    print("    wake  ordinal   status_lo  status_hi   之後_lo    等了µs")
    for _, e in sorted(recs):
        w, s0, s0h, s1, us, ordn = e[:6]
        flag = "  逾時!" if (s1 & 0x40000000) and not nowait else ""
        print(f"    {w:4d} {ordn:8d}   {s0:08x}   {s0h:08x}   {s1:08x}  {us:6d}{flag}")


for p in sys.argv[1:] or sys.exit(__doc__):
    show(p)
