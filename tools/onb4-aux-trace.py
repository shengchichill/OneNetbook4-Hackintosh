#!/usr/bin/env python3
"""解析 WEX ⑭ 的 ONB4AuxTrace（DDI A 每筆 RunAUX 完成時的結果與 AUX/面板電源暫存器）。

用法：python3 tools/onb4-aux-trace.py <ioreg.txt> [--fail] [--since 秒]
預設列最近 64 筆；--fail 列前 32 筆失敗。暫存器只在跟前一筆不同時列出（第一筆全列）。
AUX_CH_CTL（0x64010）：bit31 SEND_BUSY、bit30 DONE、bit29 中斷、bit28 TIME_OUT_ERROR、bits27:26 逾時設定、
  bit25 RECEIVE_ERROR、bits24:20 訊息大小、bits4:0 sync pulse 等。
"""
import re
import struct
import sys

NAMES = {0x64010: "AUX_CTL", 0x64014: "AUX_D1", 0x64018: "AUX_D2", 0x6401C: "AUX_D3", 0x64020: "AUX_D4",
         0x64024: "AUX_D5", 0xC7200: "PP_STATUS", 0xC7204: "PP_CTL", 0xC4000: "SDEISR", 0x45440: "PW_AUX1",
         0x45444: "PW_AUX2", 0x45450: "PW_DDI1", 0x45454: "PW_DDI2", 0x45504: "DC_STATE", 0x64000: "DDI_BUF",
         0x46010: "DPLL0_EN"}


def ctl(v):
    f = [n for b, n in ((31, "BUSY"), (30, "DONE"), (28, "TIMEOUT"), (25, "RXERR")) if v >> b & 1]
    return f"{v:#010x}[{','.join(f)} size={v >> 20 & 0x1f}]"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    since = float(sys.argv[sys.argv.index("--since") + 1]) if "--since" in sys.argv else 0.0
    m = re.search(r'"ONB4AuxTrace" = <([0-9a-fA-F]*)>', open(args[0]).read())
    if not m:
        sys.exit("找不到 ONB4AuxTrace（WEX ⑭ 沒載入？）")
    raw = bytes.fromhex(m.group(1))
    ver, total, fails, rsz = struct.unpack_from("<4I", raw)
    regs = struct.unpack_from("<16I", raw, 16)
    off = 16 + 64
    recs = []
    for i in range(32 + 64):
        ns, seq, res, cmd, a, hdr, rep = struct.unpack_from("<Q6I", raw, off)
        r = struct.unpack_from("<16I", raw, off + 40)
        recs.append(("fail" if i < 32 else "last", ns, seq, res, cmd, a, hdr, rep, r))
        off += rsz
    want = "fail" if "--fail" in sys.argv else "last"
    sel = sorted((x for x in recs if x[0] == want and x[2]), key=lambda x: x[2])
    print(f"ONB4AuxTrace v{ver}: 總 {total} 筆、失敗 {fails} 筆；列出 {want} {len(sel)} 筆")
    prev = None
    for _, ns, seq, res, cmd, a, hdr, rep, r in sel:
        t = ns / 1e9
        if t < since:
            continue
        st = "ok" if res == 0 else f"ERR {res:#x}"
        print(f"{seq:6} {t:10.3f}s cmd={cmd:#x} len/flag={a:#x} hdr={hdr:#010x} reply={rep:#010x} {st}")
        for k, (addr, v) in enumerate(zip(regs, r)):
            if prev is None or prev[k] != v:
                s = ctl(v) if addr == 0x64010 else f"{v:#010x}"
                print(f"         {NAMES.get(addr, hex(addr)):9} {s}")
        prev = r


if __name__ == "__main__":
    main()
