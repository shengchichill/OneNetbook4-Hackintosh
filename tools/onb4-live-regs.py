#!/usr/bin/env python3
"""解析 WEX ⑰ 的 ONB4LiveRegs（ioreg 讀取當下的顯示 plane/pipe/DBUF/PSR 暫存器 + GGTT PTE），可多份並排比對。
用法：
  ssh user@<IP> 'ioreg -p IOService -d 1 -l -w0' > teal.txt
  python3 tools/onb4-live-regs.py cold.txt teal.txt dpms.txt [--all]
預設只列各欄不全相同的暫存器（加 --all 全列）。FRMCOUNT 每次都會不同，請連讀兩次看 pipe 有沒有在跑。
"""
import re
import struct
import sys

NAMES = {
    0x45008: "DBUF_CTL_S1", 0x44FE8: "DBUF_CTL_S2", 0x45038: "MBUS_ABOX_CTL", 0x45504: "DC_STATE_EN",
    0x45404: "PWR_WELL_CTL2", 0x46000: "CDCLK_CTL",
    0x44400: "DE_PIPE_ISR_A", 0x44404: "DE_PIPE_IMR_A", 0x44408: "DE_PIPE_IIR_A", 0x4440C: "DE_PIPE_IER_A",
    0x44410: "DE_PIPE_ISR_B", 0x44418: "DE_PIPE_IIR_B",
    0x70008: "TRANSCONF_A", 0x70030: "PIPE_MISC_A", 0x70034: "BOTTOM_COLOR_A", 0x6001C: "PIPESRC_A",
    0x70040: "FRMCOUNT_A", 0x70044: "FLIPCOUNT_A", 0x60400: "TRANS_DDI_A", 0x60000: "HTOTAL_A", 0x6000C: "VTOTAL_A",
    0x4A480: "GAMMA_MODE_A", 0x49028: "CSC_MODE_A", 0x4A400: "PAL_PREC_IDX_A",
    0x70180: "PLANE_CTL_1_A", 0x70188: "PLANE_STRIDE_1_A", 0x7018C: "PLANE_POS_1_A", 0x70190: "PLANE_SIZE_1_A",
    0x7019C: "PLANE_SURF_1_A", 0x701A4: "PLANE_OFFSET_1_A", 0x701AC: "PLANE_SURFLIVE_1_A", 0x701CC: "PLANE_COLOR_CTL_1_A", 0x701C0: "PLANE_AUX_DIST_1_A", 0x701C4: "PLANE_AUX_OFFSET_1_A",
    0x7027C: "PLANE_BUF_CFG_1_A", 0x70240: "PLANE_WM_1_A_0", 0x70268: "PLANE_WM_TRANS_1_A",
    0x70280: "PLANE_CTL_2_A", 0x7029C: "PLANE_SURF_2_A", 0x7037C: "PLANE_BUF_CFG_2_A", 0x70380: "PLANE_CTL_3_A",
    0x70080: "CUR_CTL_A", 0x70084: "CUR_BASE_A", 0x70088: "CUR_POS_A", 0x700AC: "CUR_SURFLIVE_A", 0x7017C: "CUR_BUF_CFG_A",
    0x60800: "PSR_CTL_A", 0x60840: "PSR_STATUS_A", 0x60900: "PSR2_CTL_A", 0x60940: "PSR2_STATUS_A",
    0x71008: "TRANSCONF_B", 0x71180: "PLANE_CTL_1_B", 0x7119C: "PLANE_SURF_1_B", 0x71080: "CUR_CTL_B", 0x71040: "FRMCOUNT_B",
    0xC7200: "PP_STATUS", 0x64000: "DDI_BUF_CTL_A",
    0x44050: "DERRMR", 0x44054: "DERRMR2", 0x70000: "PIPEDSL_A", 0x170000: "PIPEDSL_A#2",  # ㉑（#2 = 同一次讀取的第二次）
}
PTE_LABELS = ["PLANE_SURF_1_A", "PLANE_SURFLIVE_1_A", "CUR_BASE_A"]


def decode(path):
    text = open(path, errors="replace").read()
    m = re.search(r'"ONB4LiveRegs" = <([0-9a-fA-F]*)>', text)
    if not m:
        sys.exit(f"{path}: 找不到 ONB4LiveRegs（WEX ⑰ 沒載入？）")
    raw = bytes.fromhex(m.group(1))
    ver, n, size, ptes_ok = struct.unpack_from("<4I", raw)
    regs = {}
    off = 16
    for _ in range(n):
        a, v = struct.unpack_from("<2I", raw, off)
        regs[a + 0x100000 if a in regs else a] = v
        off += 8
    ptes = []
    for _ in range(3 if n else 0):
        addr, pad, p0, pmid, plast, x, zeros = struct.unpack_from("<2I5Q", raw, off)
        ptes.append((addr, pad, p0, pmid, plast, x, zeros))
        off += 48
    return dict(ver=ver, n=n, size=size, ptes_ok=ptes_ok, regs=regs, ptes=ptes)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show_all = "--all" in sys.argv
    if not args:
        sys.exit(__doc__)
    ds = [decode(p) for p in args]
    w = max(10, *(len(p.rsplit("/", 1)[-1]) for p in args))
    print("檔案：" + "  ".join(f"[{i}] {p}" for i, p in enumerate(args)))
    print(f"mapSize: " + "  ".join(f"0x{d['size']:x} ptesOK={d['ptes_ok']}" for d in ds))
    print(f"\n{'暫存器':22}{'addr':>9}  " + "".join(f"{'['+str(i)+']':>{w}}" for i in range(len(ds))))
    for addr in ds[0]["regs"]:
        vals = [d["regs"].get(addr) for d in ds]
        if not show_all and len(set(vals)) == 1:
            continue
        cells = "".join(f"{('%08x' % v) if v is not None else '-':>{w}}" for v in vals)
        print(f"{NAMES.get(addr, '?'):22}{addr:>#9x}  {cells}")
    print("\nGGTT PTE（每組 4096 頁 = 16 MB 從該 gfx 位址起）：")
    for k, label in enumerate(PTE_LABELS):
        print(f"  {label}")
        for i, d in enumerate(ds):
            if k >= len(d["ptes"]):
                continue
            addr, pad, p0, pmid, plast, x, zeros = d["ptes"][k]
            note = " 超出可讀範圍" if pad else ""
            print(f"    [{i}] gfx=0x{addr:08x} pte0={p0:016x} mid={pmid:016x} last={plast:016x} "
                  f"xor={x:016x} zeroPTEs={zeros}{note}")


if __name__ == "__main__":
    main()
