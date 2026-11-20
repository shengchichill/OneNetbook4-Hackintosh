#!/usr/bin/env python3
"""解析 WEX ⑦ 的 ONB4WakeTrace（S3 喚醒 eDP 診斷快照）。

用法：
  ssh user@<IP> 'ioreg -p IOService -d 1 -l -w0' | python3 tools/onb4-wake-trace.py
  python3 tools/onb4-wake-trace.py ioreg.txt
"""
import re
import struct
import sys

REGS = [
    (0xC4000, "SDEISR"), (0xC4004, "SDEIMR"), (0xC400C, "SDEIER"),
    (0xC4030, "SHOTPLUG_DDI"), (0xC4034, "SHOTPLUG_TC"), (0xC4038, "SHPD_FILT"),
    (0xC7200, "PP_STATUS"), (0xC7204, "PP_CONTROL"), (0xC7208, "PP_ON"), (0xC720C, "PP_OFF"),
    (0x45400, "PWR_WELL1"), (0x45404, "PWR_WELL2"), (0x45444, "PWR_AUX2"), (0x45504, "DC_STATE"),
    (0x46000, "CDCLK_CTL"), (0x164280, "DPCLKA_CFG0"),
    (0x64000, "DDI_BUF_A"), (0x60400, "TRANS_DDI_A"), (0x60540, "DP_TP_CTL_A"), (0x60544, "DP_TP_STS_A"),
    (0x162014, "PORT_CL_DW5"), (0x162100, "COMP_DW0"), (0x16210C, "COMP_DW3"), (0x64C00, "PHY_MISC_A"),
]
REGS_V8 = REGS + [
    (0x45454, "PWR_DDI2"), (0x162028, "PORT_CL_DW10"), (0x162804, "PCS_DW1_LN0"),
    (0x162888, "TX_DW2_LN0"), (0x162890, "TX_DW4_LN0"), (0x162894, "TX_DW5_LN0"), (0x16289C, "TX_DW7_LN0"),
    (0x162988, "TX_DW2_LN1"), (0x162990, "TX_DW4_LN1"), (0x162994, "TX_DW5_LN1"), (0x16299C, "TX_DW7_LN1"),
    (0x162A94, "TX_DW5_LN2"),
]
REGS_V9 = REGS_V8[:-1] + [(0x162120, "COMP_DW8")]
REGS_V10 = REGS_V9 + [(0x1628A0, "TX_DW8_LN0"), (0x1629A0, "TX_DW8_LN1"), (0x162904, "PCS_DW1_LN1"), (0x162AA0, "TX_DW8_LN2")]
TAGS = {1: "EnableIRQ", 2: "HPDfix", 3: "PanelPwr>", 4: "PanelPwr<", 5: "LinkTrain>", 6: "LinkTrain<", 7: "VSwing", 8: "ComboPhy>", 9: "ComboPhy<"}


def decode(text):
    m = re.search(r'"ONB4WakeTrace" = <([0-9a-fA-F]+)>', text)
    if not m:
        sys.exit("找不到 ONB4WakeTrace（WEX ⑦ 沒載入？）")
    raw = bytes.fromhex(m.group(1))
    ver, count, fix_on, fixes = struct.unpack_from("<4I", raw)
    print(f"version={ver} snapshots={count} hpdFixEnabled={fix_on} hpdFixes={fixes}")
    hdr = 16
    if ver >= 10:
        h = struct.unpack_from("<16I", raw)
        print(f"dccFixes={h[4]} bootSaved={h[5]}" + (f" lane4Fixes={h[14]}" if ver >= 11 else "")
              + (f" tps: port+0xFB={h[15] & 0xff} port+0x12={(h[15] >> 8) & 0xff} tps3Fixes={h[15] >> 16}" if ver >= 12 else ""))
        print("boot TX_DW8  LN0..3: " + " ".join(f"{v:08x}" for v in h[6:10]))
        print("boot PCS_DW1 LN0..3: " + " ".join(f"{v:08x}" for v in h[10:14]))
        hdr = 64
    regs_def, nslots = (REGS_V10, 256) if ver >= 10 else (REGS_V9, 256) if ver >= 9 else (REGS_V8, 256) if ver >= 8 else (REGS, 128)
    SNAP = struct.Struct(f"<QII{len(regs_def)}I")
    slots = []
    for i in range(nslots):
        ns, tag, arg, *regs = SNAP.unpack_from(raw, hdr + i * SNAP.size)
        if tag:
            slots.append((ns, i, tag, arg, regs))
    # 依時間排序（環狀區會被覆寫，用時間戳還原順序；睡眠期間時鐘不走）
    slots.sort()
    prev = None
    for ns, i, tag, arg, regs in slots:
        print(f"\n[{i:3}] t={ns / 1e9:10.3f}s {TAGS.get(tag, tag):10} arg=0x{arg:x}")
        for (addr, name), v in zip(regs_def, regs):
            mark = ""
            if prev is not None and prev[addr] != v:
                mark = f"   (was 0x{prev[addr]:08x})"
            print(f"    {name:12} {addr:#08x} = 0x{v:08x}{mark}")
        prev = dict(zip((a for a, _ in regs_def), regs))
    print("\n提示：SDEISR bit16 = DDI A HPD；SHOTPLUG_DDI bit3 = DDI A HPD 致能；"
          "PP_STATUS bit31 = 面板電源開、bit27 = power cycle 延遲中；"
          "v9：COMP_DW8 bit24 = IREFGEN；hpdFixEnabled bit0=HPD bit1=IREFGEN，hpdFixes 低 16=HPD 高 16=IREFGEN；"
          "v10：flags bit2=DCC（v11 bit3=lane4，v12 bit4=TPS3）；ComboPhy arg bit9=ODCC/DCC 有改、bit10=用開機值；TX_DW8 bit31=ODCC_CLK_SEL bits30:29=DIV；PCS_DW1 bits21:20=DCC mode")


if __name__ == "__main__":
    decode(open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read())
