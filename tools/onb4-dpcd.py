#!/usr/bin/env python3
"""解析 WEX 的 DPCD/AUX 交易紀錄（WhateverXeDPCDLive = 最近 128 筆、WhateverXeDPCDFirst = 開機起前 1024 筆）。

用法：python3 tools/onb4-dpcd.py <ioreg.txt> [--first] [--since 秒] [--ddi N]（預設只列 DDI A=0；--ddi -1 全列）
每筆：序號、時間、R/W、DPCD 位址、長度、完成/結果、資料。
紀錄格式（kern_xe.cpp TGLDPCDRecord，80 bytes）：u64 ns, u64 thread, u32 w[16]
  w0 序號 w1 位址 w2 長度 w3 write w4 done w5 result w6 資料長度 w7 caller w8..11 資料 w12 port
"""
import re
import struct
import sys

NAMES = {0x100: "LINK_BW", 0x101: "LANE_COUNT", 0x102: "TRAINING_PATTERN", 0x103: "TRAIN_LANE0",
         0x107: "DOWNSPREAD", 0x108: "MAIN_LINK_CODING", 0x115: "eDP_RATE_SEL", 0x170: "PSR_EN",
         0x200: "SINK_COUNT", 0x202: "LANE01_STATUS", 0x204: "ALIGN_STATUS", 0x206: "ADJUST_REQ",
         0x600: "SET_POWER", 0x000: "DPCD_REV", 0x00e: "TRAIN_AUX_RD_INTERVAL"}


def records(text, key):
    m = re.search(rf'"{key}" = <([0-9a-fA-F]*)>', text)
    if not m:
        return []
    raw = bytes.fromhex(m.group(1))
    if key == "WhateverXeDPCDLive":
        raw = raw[16:]
    out = []
    for off in range(0, len(raw) - 79, 80):
        ns, th = struct.unpack_from("<QQ", raw, off)
        w = struct.unpack_from("<16I", raw, off + 16)
        if w[0] == 0:
            continue
        out.append((w[0], ns, th, w))
    out.sort()
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    key = "WhateverXeDPCDFirst" if "--first" in sys.argv else "WhateverXeDPCDLive"
    since = 0.0
    if "--since" in sys.argv:
        since = float(sys.argv[sys.argv.index("--since") + 1])
    ddi = int(sys.argv[sys.argv.index("--ddi") + 1]) if "--ddi" in sys.argv else 0
    recs = records(open(args[0]).read(), key)
    print(f"{key}: {len(recs)} 筆")
    for seq, ns, th, w in recs:
        t = ns / 1e9
        if t < since or (ddi >= 0 and w[12] != ddi):
            continue
        addr, ln, wr, done, res, dl = w[1], w[2], w[3], w[4], w[5], w[6]
        data = struct.pack("<4I", *w[8:12])[:dl].hex(" ")
        name = NAMES.get(addr, "")
        st = ("ok" if res == 0 else f"ERR {res:#x}") if done else "start"
        if not done and not wr:
            continue  # 讀取的 start 沒有資料，略過
        print(f"{seq:6} {t:10.3f}s D{w[12]} {'W' if wr else 'R'} {addr:#05x} {name:16} len={ln:2} {st:14} {data}")


if __name__ == "__main__":
    main()
