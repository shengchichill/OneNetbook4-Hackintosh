#!/usr/bin/env python3
"""最小的 Intel VBT 解析：只印 eDP 相關欄位（panel type、fast link params、色深、child devices）。

結構依 Linux drivers/gpu/drm/i915/display/intel_vbt_defs.h（v6.12）。
用法：python3 scripts/vbt-edp.py build/logs/fedora-edp/vbt.bin
"""
import struct, sys

d = open(sys.argv[1], "rb").read()
assert d[:4] == b"$VBT", "not a VBT"
bdb_off = struct.unpack_from("<I", d, 0x1C)[0]
assert d[bdb_off:bdb_off + 16] == b"BIOS_DATA_BLOCK ", "BDB signature missing"
ver, hsize, bsize = struct.unpack_from("<HHH", d, bdb_off + 16)
print(f"VBT {d[4:20].rstrip(b'\0 ').decode(errors='replace')}  BDB version {ver}")

blocks = {}
p = bdb_off + hsize
end = bdb_off + bsize
while p + 3 <= end:
    bid = d[p]
    size = struct.unpack_from("<H", d, p + 1)[0]
    if bid == 0 and size == 0:
        break
    blocks[bid] = d[p + 3:p + 3 + size]
    p += 3 + size
print("blocks:", sorted(blocks))

panel_type = None
if 40 in blocks:
    panel_type = blocks[40][0]
    print(f"\n[LFP options #40] panel_type = {panel_type}")

DVO = {0: "HDMI-A", 1: "HDMI-B", 2: "HDMI-C", 3: "HDMI-D", 6: "DP-B", 7: "DP-C", 8: "DP-D",
       10: "DP-A(eDP)", 11: "DP-E", 12: "HDMI-E", 13: "DP-F", 14: "HDMI-F",
       15: "DP-G", 16: "HDMI-G", 17: "DP-H", 18: "HDMI-H", 19: "DP-I", 20: "HDMI-I"}
AUX = {0x40: "AUX-A", 0x10: "AUX-B", 0x20: "AUX-C", 0x30: "AUX-D", 0x50: "AUX-E", 0x60: "AUX-F",
       0x70: "AUX-G", 0x80: "AUX-H", 0x90: "AUX-I"}

if 2 in blocks:
    b = blocks[2]
    csize = b[4]
    print(f"\n[General definitions #2] child_dev_size = {csize}")
    for i in range((len(b) - 5) // csize):
        c = b[5 + i * csize:5 + (i + 1) * csize]
        handle, dtype = struct.unpack_from("<HH", c, 0)
        if dtype == 0:
            continue
        dvo = c[0x10]
        f17 = c[0x17]
        aux = c[0x19] if csize > 0x19 else None
        line = (f"  child {i}: handle=0x{handle:04x} type=0x{dtype:04x} dvo_port={dvo}({DVO.get(dvo, '?')}) "
                f"aux=0x{aux:02x}({AUX.get(aux, '?')}) "
                f"lane_reversal={(f17 >> 1) & 1} dp_max_lane_count(raw,v244+)={(f17 >> 6) & 3}")
        if csize > 0x27:
            line += f" dp_max_link_rate(raw,v216+)={c[0x27] & 7}"
        print(line)
        print("           raw:", c.hex())

if 27 in blocks:
    b = blocks[27]
    print(f"\n[eDP #27] size {len(b)}")
    o = 16 * 10  # 16 x edp_power_seq (5 x u16)
    color_depth = struct.unpack_from("<I", b, o)[0]; o += 4
    fast = b[o:o + 32]; o += 32
    RATE = {0: "1.62 (RBR)", 1: "2.7 (HBR)", 2: "5.4 (HBR2)", 3: "8.1 (HBR3)"}
    LANES = {0: 1, 1: 2, 3: 4}
    for pt in sorted({panel_type} if panel_type is not None else range(16)):
        if pt is None or pt > 15:
            continue
        bpp = {0: 18, 1: 24, 2: 30, 3: 36}[(color_depth >> (pt * 2)) & 3]
        f0, f1 = fast[pt * 2], fast[pt * 2 + 1]
        print(f"  panel {pt}: color_depth -> {bpp} bpp; fast_link rate={RATE.get(f0 & 15, f0 & 15)} "
              f"lanes={LANES.get(f0 >> 4, f0 >> 4)} preemph={f1 & 15} vswing={f1 >> 4}")
    print("  fast_link_params raw:", fast.hex())
    # 後續欄位依 BDB 版本附加；只在版本夠新時印出 v244 的 max port link rate
    if ver >= 244 and panel_type is not None:
        o += 4 + 2 + 2 + 8 + 2 + 2 + 16 * 4 + 2 + 16  # sdrrs, s3d, t3, vswing, flt, 600h, pwm, full_params_provided, full_params
        o += 2 + 4 * 5  # apical_enable, apical_params (5 x u32)
        if ver >= 224:
            flt_rate = struct.unpack_from("<H", b, o + pt * 2)[0]
            print(f"  edp_fast_link_training_rate[{pt}] = {flt_rate} (x200 kHz units)")
        o += 32
        if o + 32 <= len(b):
            mx = struct.unpack_from("<H", b, o + pt * 2)[0]
            print(f"  edp_max_port_link_rate[{pt}] = {mx} (x20 MHz units, 0 = no limit)")
