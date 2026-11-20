#!/usr/bin/env python3
"""解析 WEX ㉒ 的 ONB4GTRegs（GT 端暫存器快照：開機一份 + 每次 onb4WakeCount 變動後 10 s 一份）。
用法：
  ssh user@<IP> 'ioreg -p IOService -d 1 -l -w0' > x.txt
  python3 tools/onb4-gt-regs.py x.txt [--all]
預設只列「任一快照與開機那份（slot0）不同」的暫存器；--all 全列。
已知會自己變的（RC_STATE、RPNSWREQ 等）標 *，判讀時先忽略。
"""
import re
import struct
import sys

NAMES = {
    0x2050: "RCS_PSMI_CTL", 0x2080: "RCS_HWS_PGA", 0x2098: "RCS_HWSTAM", 0x209C: "RCS_MI_MODE", 0x20A0: "FF_THREAD_MODE",
    0x20A8: "RCS_IMR", 0x20C4: "RCS_CMD_CCTL", 0x20D4: "CSFE_CHICKEN1", 0x2244: "RCS_CTX_CTRL", 0x229C: "RCS_GFX_MODE",
    0x2580: "CS_CHICKEN1", 0x2209C: "BCS_MI_MODE", 0x220A8: "BCS_IMR", 0x2229C: "BCS_GFX_MODE",
    0x7000: "CACHE_MODE_0", 0x7004: "CACHE_MODE_1", 0x7008: "GT_MODE", 0x7010: "COMMON_SLICE_CHICKEN1",
    0x7014: "COMMON_SLICE_CHICKEN2", 0x7034: "L3CNTLREG", 0x7300: "0x7300", 0x7304: "CSC3/HDC_CHICKEN", 0x6604: "FF_MODE2*",
    0xE18C: "SAMPLER_MODE", 0xE194: "HALF_SLICE_CHICKEN7", 0xE420: "CACHE_MODE_SS", 0xE48C: "ROW_CHICKEN4",
    0xE4F0: "ROW_CHICKEN", 0xE4F4: "ROW_CHICKEN2",
    0x4080: "GAMW_ECO_DEV_RW_IA", 0x4094: "0x4094", 0x4AB0: "GAMT_ECO_REG_RW_IA", 0xB004: "GARBCNTL",
    0xB118: "L3SQCREG4", 0xB404: "GLBLINVL", 0xB43C: "LSN_UNSLCVC",
    0x9400: "UCGCTL1", 0x9404: "UCGCTL2", 0x941C: "0x941C", 0x9424: "MISCCPCTL", 0x9430: "UCGCTL6", 0x94D4: "SUBSLICE_CLKGATE",
    0xA008: "RPNSWREQ*", 0xA024: "RP_CONTROL", 0xA090: "RC_CONTROL", 0xA094: "RC_STATE*", 0xA0A8: "RC_EVAL_INTERVAL",
    0xA0AC: "RC_IDLE_HYSTERSIS", 0xA0B8: "RC6_THRESHOLD", 0xA0C4: "MEDIA_PG_IDLE_HYST", 0xA0C8: "RENDER_PG_IDLE_HYST",
    0xA180: "0xA180", 0xA210: "PG_ENABLE",
    0x190010: "GFX_MSTR_IRQ*", 0x190030: "RENDER_COPY_INTR_EN", 0x190034: "VCS_VECS_INTR_EN", 0x190040: "GUC_SG_INTR_EN",
    0x190090: "RCS0_RSVD_INTR_MASK", 0x1900A8: "BCS_RSVD_INTR_MASK",
}
for i in range(64):
    NAMES[0x4000 + i * 4] = f"GLOBAL_MOCS[{i}]"
for i in range(32):
    NAMES[0xB020 + i * 4] = f"L3CC[{i}]"
for i in range(8):
    NAMES[0x4800 + i * 4] = f"PAT_INDEX[{i}]"


def decode(path):
    text = open(path, errors="replace").read()
    m = re.search(r'"ONB4GTRegs" = <([0-9a-fA-F]*)>', text)
    if not m:
        sys.exit(f"{path}: 找不到 ONB4GTRegs（WEX ㉒ 沒載入？）")
    raw = bytes.fromhex(m.group(1))
    ver, n, taken, slots = struct.unpack_from("<4I", raw)
    hl = 16
    diag = None
    if ver >= 2:  # ㉒b：calls, ackFail, lastAck, pending
        diag = struct.unpack_from("<4I", raw, 16)
        hl = 32
    addrs = struct.unpack_from(f"<{n}I", raw, hl)
    off = hl + 4 * n
    snaps = []
    for s in range(slots):
        ns, wake, ack = struct.unpack_from("<QII", raw, off)
        vals = struct.unpack_from(f"<{n}I", raw, off + 16)
        off += (16 + 4 * n + 7) & ~7  # C struct 對齊到 8（u64 ns）
        if ns:
            snaps.append((s, ns, wake, ack, vals))
    return ver, taken, addrs, snaps, diag


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    show_all = "--all" in sys.argv
    for p in args:
        ver, taken, addrs, snaps, diag = decode(p)
        print(f"== {p}  ver={ver} 已取 {taken} 份（slot0=開機，其餘環狀）")
        if diag:
            print(f"  診斷：呼叫 {diag[0]} 次、ack 失敗 {diag[1]} 次、最後 ack={diag[2]:#010x}（低16=GT 0x130044、高16=render 0xD84）、pending={diag[3]}")
        snaps.sort(key=lambda x: x[1])
        for s, ns, wake, ack, _ in snaps:
            flags = []
            if ack & 0x20000000: flags.append("㉒c 自持 fw(bit3)")
            if ack & 0x10000000: flags.append("【喚醒後第一份】")
            if ack & 0x80000000: flags.append("⚠ 強制取樣（沒拿到 forcewake，GT 域值不可信）")
            if ack & 0x40000000: flags.append("⚠ 讀取途中 forcewake 掉了")
            print(f"  slot{s}: t={ns / 1e9:9.1f}s wakeCount={wake} ack={ack & 0x0FFFFFFF:#010x} {' '.join(flags)}")
        if not snaps:
            continue
        base = next(x for x in snaps if x[0] == 0)[4] if any(x[0] == 0 for x in snaps) else snaps[0][4]
        hdr = "".join(f"{'slot' + str(x[0]):>11}" for x in snaps)
        print(f"\n  {'暫存器':24}{'addr':>9}{hdr}")
        diff = 0
        for i, a in enumerate(addrs):
            vals = [x[4][i] for x in snaps]
            if not show_all and all(v == base[i] for v in vals):
                continue
            diff += 1
            cells = "".join(f"{v:>11x}" if v == base[i] else f"{'!' + format(v, 'x'):>11}" for v in vals)
            print(f"  {NAMES.get(a, '?'):24}{a:>#9x}{cells}")
        print(f"\n  與開機不同的暫存器：{diff} 個（! = 與 slot0 不同；* = 本來就會變）")


main()
