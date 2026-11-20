#!/usr/bin/env python3
"""解析 WEX ⑫ 的 ONB4PhyDump（linkTraining 出口整段 PHY/DPLL dump），並可與 Linux regdump 並排比對。

用法：
  python3 tools/onb4-phy-dump.py <macOS ioreg.txt> [Linux onb4-regdump-*.txt ...] [--all]
欄位：mac0 = 第一次成功（開機）、mac1 = 第一次失敗、mac2 = 最近一次；之後是各 Linux 檔。
預設只列出各欄不全相同的位址；--all 全列。
"""
import re
import struct
import sys


def mac_dump(text):
    m = re.search(r'"ONB4PhyDump" = <([0-9a-fA-F]+)>', text)
    if not m:
        sys.exit("找不到 ONB4PhyDump（WEX ⑫ 沒載入？）")
    raw = bytes.fromhex(m.group(1))
    ver, nr, nw, seq = struct.unpack_from("<4I", raw)
    ranges = [struct.unpack_from("<2I", raw, 16 + 8 * i) for i in range(nr)]
    addrs = [base + 4 * i for base, n in ranges for i in range(n)]
    off = 16 + 8 * nr
    slots = []
    for _ in range(3):
        ns, valid, result, sq, _pad = struct.unpack_from("<QIIII", raw, off)
        words = struct.unpack_from(f"<{nw}I", raw, off + 24)
        off += 24 + 4 * nw
        slots.append((valid, ns, result, sq, dict(zip(addrs, words)) if valid else {}))
    return seq, addrs, slots


def linux_dump(path):
    d = {}
    for line in open(path):
        m = re.search(r"\(0x([0-9a-f]+)\):\s*0x([0-9a-f]+)", line)
        if m:
            d[int(m.group(1), 16)] = int(m.group(2), 16)
    return d


def main():
    args = [a for a in sys.argv[1:] if a != "--all"]
    show_all = "--all" in sys.argv
    seq, addrs, slots = mac_dump(open(args[0]).read())
    cols, names = [], []
    print(f"dump seq={seq}")
    for i, (valid, ns, result, sq, d) in enumerate(slots):
        print(f"  mac{i}: " + (f"t={ns / 1e9:.3f}s result=0x{result:x} seq={sq}" if valid else "（空）"))
        cols.append(d)
        names.append(f"mac{i}")
    for p in args[1:]:
        cols.append(linux_dump(p))
        names.append(p.rsplit("/", 1)[-1].replace("onb4-regdump-", "lx-").replace(".txt", ""))
    print("\n  addr     " + " ".join(f"{n:>10}" for n in names))
    for a in addrs:
        vals = [c.get(a) for c in cols]
        present = [v for v in vals if v is not None]
        if not show_all and len(set(present)) <= 1:
            continue
        print(f"  {a:#08x} " + " ".join(f"{v:10x}" if v is not None else f"{'-':>10}" for v in vals))


if __name__ == "__main__":
    main()
