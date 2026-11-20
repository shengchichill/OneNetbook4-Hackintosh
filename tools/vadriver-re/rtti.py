# Map C++ RTTI names -> typeinfo -> vtable addresses in a non-PIE-chained x86_64 Mach-O (raw pointers in data).
# Usage: python3 -I rtti.py <Mach-O> [class-name regex]   (TGL VA driver static analysis, see docs/HANDOFF.md "影片播放")
import struct, sys, re
data = open(sys.argv[1], 'rb').read()
ncmds = struct.unpack_from('<I', data, 16)[0]
off = 32; segs = []
for _ in range(ncmds):
    cmd, sz = struct.unpack_from('<II', data, off)
    if cmd == 0x19:
        segname = data[off+8:off+24].rstrip(b'\0').decode()
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', data, off+24)
        nsects = struct.unpack_from('<I', data, off+64)[0]
        for i in range(nsects):
            s = off + 72 + i*80
            sect = data[s:s+16].rstrip(b'\0').decode()
            addr, size, foff = struct.unpack_from('<QQI', data, s+32)
            segs.append((segname, sect, addr, size, foff))
    off += sz
def a2o(a):
    for sg, sc, addr, size, foff in segs:
        if addr <= a < addr+size and foff: return foff + (a-addr)
def o2a(o):
    for sg, sc, addr, size, foff in segs:
        if foff and foff <= o < foff+size: return addr + (o-foff)
pat = re.compile(rb'\x00(N?[0-9]{1,3}[A-Za-z_][A-Za-z0-9_]{2,}E?)\x00')
names = {}
for m in pat.finditer(data):
    s = m.group(1).decode()
    mm = re.match(r'^N?([0-9]+)', s)
    names[o2a(m.start(1))] = s
# index all 8-byte aligned qwords in data sections
qw = {}
for sg, sc, addr, size, foff in segs:
    if sg in ('__DATA', '__DATA_CONST') or sc == '__const':
        if not foff: continue
        for i in range(0, size - 7, 8):
            v = struct.unpack_from('<Q', data, foff+i)[0]
            qw.setdefault(v, []).append(addr+i)
flt = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None
for na, s in sorted(names.items(), key=lambda x: x[1]):
    if flt and not flt.search(s): continue
    for ti_name_slot in qw.get(na, []):
        ti = ti_name_slot - 8
        for vt_slot in qw.get(ti, []):
            # vtable: [offset_to_top][typeinfo][fn...]; only primary (offset_to_top == 0)
            o = a2o(vt_slot - 8)
            ott = struct.unpack_from('<q', data, o)[0] if o is not None else None
            if ott == 0:
                fns = [struct.unpack_from('<Q', data, a2o(vt_slot+8+8*k))[0] for k in range(4)]
                print(f'{s:45s} typeinfo={ti:#x} vtable(fnptrs)={vt_slot+8:#x} first={[hex(f) for f in fns]}')
