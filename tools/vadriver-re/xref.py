# For given RTTI name file offsets: find typeinfo, vtables (any offset_to_top), and RIP-relative LEA/MOV xrefs in __text.
# Usage: python3 -I xref.py <Mach-O> <file offset of RTTI name string, hex>...   (see docs/HANDOFF.md "影片播放")
import struct, sys
d = open(sys.argv[1], 'rb').read()
# bundle: vmaddr == fileoff for __TEXT and __DATA here? verify via load commands
ncmds = struct.unpack_from('<I', d, 16)[0]; off = 32; segs = []
for _ in range(ncmds):
    cmd, sz = struct.unpack_from('<II', d, off)
    if cmd == 0x19:
        name = d[off+8:off+24].rstrip(b'\0').decode()
        vm, vs, fo, fs = struct.unpack_from('<QQQQ', d, off+24)
        nsects = struct.unpack_from('<I', d, off+64)[0]
        for i in range(nsects):
            s = off+72+i*80
            sec = d[s:s+16].rstrip(b'\0').decode(); a, sz2, fo2 = struct.unpack_from('<QQI', d, s+32)
            segs.append((name, sec, a, sz2, fo2))
    off += sz
o2a = lambda o: next((a+(o-f)) for (_,_,a,s,f) in segs if f and f <= o < f+s)
a2o = lambda x: next((f+(x-a)) for (_,_,a,s,f) in segs if f and a <= x < a+s)
text = next(s for s in segs if s[1] == '__text')
def qrefs(val):
    out = []; b = struct.pack('<Q', val); i = d.find(b)
    while i != -1:
        if i % 8 == 0: out.append(o2a(i))
        i = d.find(b, i+1)
    return out
def riprefs(target):
    # scan for disp32 such that next_ip + disp == target, for 7-byte lea/mov (48 8d/8b modrm 05|0d|...)
    _,_,ta,ts,tf = text; res = []
    for i in range(tf, tf+ts-7):
        if d[i] in (0x48, 0x4c) and d[i+1] in (0x8d, 0x8b) and (d[i+2] & 0xc7) == 0x05:
            disp = struct.unpack_from('<i', d, i+3)[0]
            if o2a(i)+7+disp == target: res.append(o2a(i))
    return res
for nameoff in sys.argv[2:]:
    na = o2a(int(nameoff, 16))
    print(f'name @{na:#x}')
    for slot in qrefs(na):
        ti = slot - 8; print(f'  typeinfo {ti:#x}')
        for vs in qrefs(ti):
            ott = struct.unpack_from('<q', d, a2o(vs-8))[0]
            vt = vs + 8
            refs = riprefs(vt)
            print(f'    vtable fnptrs @{vt:#x} offset_to_top={ott} text xrefs={[hex(r) for r in refs]}')
        sub = qrefs(ti)
