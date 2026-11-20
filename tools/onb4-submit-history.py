#!/usr/bin/env python3
"""解析 WEX 內建的 TGLSubmitHistory0（hang 時凍結的 RCS 送出紀錄）與 TGLSameTail0。
格式來源：WhateverXe/kern_tgl_submit_history.hpp、kern_tgl_same_tail.hpp、kern_xe.cpp tglSubmitHistoryPublish。
用法：python3 tools/onb4-submit-history.py hang-ioreg.txt [最後幾筆，預設 24]
"""
import re
import struct
import sys

REGS = [0x2030, 0x2034, 0x2038, 0x203c, 0x2064, 0x2068, 0x2074, 0x2078, 0x2084, 0x209c,
        0x2234, 0x2238, 0x2510, 0x2514, 0x21c4, 0x21c8]
R = {a: i for i, a in enumerate(REGS)}
PHASE = {0: "before", 1: "after ", 2: "preSTP"}


def blob(text, key):
    m = re.search(r'"%s" = <([0-9a-fA-F]*)>' % key, text)
    return bytes.fromhex(m.group(1)) if m else None


def main():
    path = sys.argv[1]
    last = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    text = open(path, errors="replace").read()

    st = blob(text, "TGLSameTail0")
    if st:
        # State: Entry previous(8 u64), Entry first(8 u64), counts[8]
        c = struct.unpack_from("<8Q", st, 128)
        print("TGLSameTail counts: schema=%d attempts=%d valid=%d activeRetained=%d sameTail=%d forced=%d nativeForced=%d rejected=%d" % c)

    b = blob(text, "TGLSubmitHistory0")
    if not b:
        sys.exit("找不到 TGLSubmitHistory0（沒有 hang 或未啟用 SameTail）")
    hdr = struct.unpack_from("<8Q", b, 0)
    print(f"header: schema={hdr[0]} recSize={hdr[1]} recent={hdr[2]} early={hdr[3]} attempts={hdr[4]} drops={hdr[5]} frozenAt={hdr[6]/1e9:.3f}s")
    recs = []
    off = 64
    for i in range(320):
        seq = struct.unpack_from("<Q", b, off)[0]
        q = struct.unpack_from("<16Q", b, off + 8)
        slots = [struct.unpack_from("<10Q", b, off + 8 + 128 + s * 80) for s in range(4)]
        regs = struct.unpack_from("<16I", b, off + 8 + 128 + 320)
        off += 8 + 512
        if seq and i >= 64:
            recs.append((seq, q, slots, regs))
    recs.sort()
    t_end = hdr[6]
    print(f"{'seq':>6} {'t-freeze':>9} {'ord':>6} phase  bank csbHead lastCSB          TAIL   HEAD     EXST_lo  EXST_hi  ELSP0    ELSP1   | slots: ctxID/tail/retiredStamp/cpuIdx/force")
    for seq, q, slots, regs in recs[-last:]:
        dt = (q[1] - t_end) / 1e6 if q[1] else 0
        ordn = q[3] if q[3] != 0xFFFFFFFF else -1
        sl = []
        for s in slots:
            if s[0]:
                sl.append(f"{s[9]:x}/{s[4]:x}/{s[6]:x}/{s[7]:x}/{s[8]}")
            else:
                sl.append("-")
        print(f"{seq:6d} {dt:8.1f}ms {ordn:6d} {PHASE.get(q[4], q[4])} {q[8]:4d} {q[12]:7d} {q[13]:016x} "
              f"{regs[R[0x2030]]:6x} {regs[R[0x2034]]:08x} {regs[R[0x2234]]:08x} {regs[R[0x2238]]:08x} "
              f"{regs[R[0x2510]]:08x} {regs[R[0x2514]]:08x} | {'  '.join(sl)}  err={q[10]} ack={q[14]:x}")


main()
