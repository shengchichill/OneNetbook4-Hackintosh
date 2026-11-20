#!/usr/bin/env python3
"""解析 WEX ㉑ 的 ONB4SyncTrace（IGAccelSurface::generateSync 呼叫紀錄；submitSwapFlush 的 scanline window wait）。
用法：
  ssh user@<IP> 'ioreg -p IOService -d 1 -l -w0' > x.txt
  python3 tools/onb4-sync-trace.py x.txt [y.txt ...]
欄位：t = 開機後秒數（mach uptime，S3 期間不走）、snap = 當時 onb4WakeCount（WakeTrace 快照數，S3 喚醒會增加）、
pipe = generateSync 第 2 參數（0=A）、bounds = IOAccelBounds x,y,w,h（scanline 視窗由 y、h 算）。
"""
import re
import struct
import sys


def decode(path):
    text = open(path, errors="replace").read()
    routed = re.search(r'"ONB4SyncRouted" = (\d+)', text)
    m = re.search(r'"ONB4SyncTrace" = <([0-9a-fA-F]*)>', text)
    if not m:
        sys.exit(f"{path}: 找不到 ONB4SyncTrace（WEX ㉑ 沒載入？）")
    raw = bytes.fromhex(m.group(1))
    ver, calls, skipped, nosync = struct.unpack_from("<4I", raw)
    recs = []
    for i in range(32):
        ns, snap, a, pipe, c, x, y, w, h = struct.unpack_from("<Q4I4h", raw, 16 + i * 32)
        recs.append((i, ns, snap, a, pipe, c, x, y, w, h))
    print(f"== {path}")
    print(f"ver={ver} ONB4SyncRouted={routed.group(1) if routed else '?'}（bit0 已掛、bit1 -onb4nosync）"
          f" calls={calls} skipped={skipped} nosync={nosync}")
    if not calls:
        print("  （generateSync 從未被呼叫）")
        return
    start = calls % 32 if calls > 32 else 0
    order = [(start + k) % 32 for k in range(min(calls, 32))]
    first = calls - len(order)
    for k, i in enumerate(order):
        _, ns, snap, a, pipe, c, x, y, w, h = recs[i]
        print(f"  #{first + k:<6} t={ns / 1e9:10.3f}s snap={snap:<4} a={a:#x} pipe={pipe} c={c:#x} bounds=({x},{y},{w},{h})")


for p in sys.argv[1:] or sys.exit(__doc__):
    decode(p)
