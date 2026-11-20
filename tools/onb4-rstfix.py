#!/usr/bin/env python3
"""解析 WEX ㉓ 的 ONB4RstFix（Apple resetGraphicsEngine 之後把 render 設定寫回開機值）。
用法：
  ssh user@<IP> 'ioreg -p IOService -d 1 -l -w0' > x.txt
  python3 tools/onb4-rstfix.py x.txt [--all]
列出最後一次 reset 的 {開機值, reset 後(寫之前), 寫之後}；預設只列 reset 後跟開機不同的。
"""
import re
import struct
import sys

NAMES = {0x2050: "RCS_PSMI_CTL", 0x2580: "CS_CHICKEN1", 0x7004: "CACHE_MODE_1",
         0x7300: "HDC_CHICKEN0", 0x7304: "COMMON_SLICE_CHICKEN3", 0xE48C: "ROW_CHICKEN4"}
for i in range(32):
    NAMES[0xB020 + i * 4] = f"L3CC[{i}]"
BAD = 0xDEADDEAD


def main(path, show_all):
    text = open(path, errors="replace").read()
    routed = re.search(r'"ONB4RstFixRouted" = (\d+)', text)
    m = re.search(r'"ONB4RstFix" = <([0-9a-fA-F]*)>', text)
    if not m:
        sys.exit(f"{path}: 找不到 ONB4RstFix（WEX ㉓ 沒載入？）")
    raw = bytes.fromhex(m.group(1))
    ver, calls, applied, last_ret, n, nofix, have, _ = struct.unpack_from("<8I", raw)
    r = int(routed.group(1)) if routed else -1
    print(f"== {path}  ver={ver}  routed={r & 1 if r >= 0 else '?'}{'（-onb4norstfix：只記錄）' if nofix else ''}")
    print(f"  reset 次數 {calls}、有寫回的次數 {applied}、最後回傳 {last_ret}、"
          f"開機值齊全={'是' if have & 1 else '否'}、forcewake={'有' if have & 2 else '沒拿到'}")
    if not calls:
        print("  （還沒有 reset）")
        return
    print(f"\n  {'暫存器':24} {'addr':>8} {'開機':>10} {'reset 後':>10} {'寫回後':>10}")
    shown = 0
    for i in range(n):
        a, boot, before, after = struct.unpack_from("<4I", raw, 32 + 16 * i)
        if not show_all and before == boot:
            continue
        shown += 1
        f = lambda v: "-" if v == BAD else f"{v:x}"
        ok = "" if after == boot else "  ✗ 仍不同"
        print(f"  {NAMES.get(a, hex(a)):24} {a:#8x} {f(boot):>10} {f(before):>10} {f(after):>10}{ok}")
    if not shown:
        print("  （reset 後全部跟開機相同）")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    for p in args:
        main(p, "--all" in sys.argv)
