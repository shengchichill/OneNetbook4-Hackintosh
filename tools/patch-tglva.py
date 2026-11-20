#!/usr/bin/env python3
"""Make the WhateverXe-Graphics 0.4.0 (Tahoe) TGL VA driver skip its missing VEBOX renderers.

Background (static analysis 2026-11-06, see docs/HANDOFF.md "影片播放"):
the driver's video processing is Intel media-driver VPHAL. `this+0x910` is
VphalRenderer::pRender[3] = { [0] VEBOX, [1] VEBOX2, [2] COMPOSITE }.
VphalRendererG12::AllocateRenderComponents (0x1b1bc0) only creates CompositeStateG12;
there is no G12 VEBOX renderer class in the binary at all, so [0]/[1] stay NULL.
The pkg author guards Initialize() (trampolines 0xd80/0xd98); three sites are left:

  A 0x1336e8  pRender[VEBOX]->reporting = this+0x2cb0            -> skip when NULL
  B 0x130e80  pRender[VEBOX+ch]->SetStatusReportParams(...)      -> skip when NULL
  C 0x12d2dc  VEBOX dispatch (called from RenderSingleStream): calls a virtual on
              pRender[VEBOX+ch] before its own NULL check        -> when NULL, act as if
              VEBOX is disabled: bCompNeeded(+8)=1, bSfcOnly(+0x20)=0, return 0,
              so the frame goes to CompositeStateG12 (EU kernels) instead.
              Needs a 17-byte cave: header padding at 0x1100 (zero run 0x10d3..0x1160,
              inside __TEXT r-x, before __text at 0x1160).

__TEXT vmaddr 0 / fileoff 0, so vmaddr == file offset.
Usage: patch-tglva.py <in AppleIntelTGLGraphicsVADriver> <out>
Then: copy the bundle, replace the binary, `codesign -f -s - <bundle>`.
"""
import hashlib
import struct
import sys

ORIG_SHA256 = "a972cdb7ddd56bcf38c3ab71e874b73efc34bc683d30e49f0a1a1919625a726d"  # WhateverXe-Graphics 0.4.0 Tahoe


def rel32(src_next, dst):
    return struct.pack("<i", dst - src_next)


CAVE = 0x1100

# A: 0x1336e8..0x133700 (24 bytes); rdx = this+0x2cb0 here, so this+0x910 = rdx-0x23a0
A_OLD = bytes.fromhex("488b4dd8" "488bb910090000" "48895708" "8b45e4" "4883c430" "5d" "c3")
A_NEW = bytes.fromhex("488bba60dcffff" "4885ff" "7404" "48895708" "8b45e4" "c9" "c3")
A_NEW += b"\x90" * (len(A_OLD) - len(A_NEW))

# B: 0x130e80..0x130ea5 (37 bytes)
B_OLD = bytes.fromhex("488b45a0" "8b88bc090000" "83c100" "89c9" "89ca" "488bbcd010090000"
                      "488b55f0" "4889c6" "e87b56ffff")
B_NEW = (bytes.fromhex("9090"
                       "488b45a0"            # mov rax,[rbp-0x60]          ; renderer
                       "8b88bc090000"        # mov ecx,[rax+0x9bc]         ; uiCurrentChannel
                       "488bbcc810090000"    # mov rdi,[rax+rcx*8+0x910]   ; pRender[VEBOX+ch]
                       "4885ff"              # test rdi,rdi
                       "740c"                # je 0x130ea5 (skip call)
                       "488b55f0"            # mov rdx,[rbp-0x10]
                       "4889c6")             # mov rsi,rax
         + b"\xe8" + rel32(0x130ea5, 0x126520))  # call SetStatusReportParams

# C: 0x12d2dc..0x12d2f9 (29 bytes), falls through to `mov [rbp-0x30],rax`
C_OLD = bytes.fromhex("488b45f8" "488b4df8" "8b91bc090000" "83c200" "89d2" "89d1" "488b84c810090000")
C_NEW = (bytes.fromhex("488b45f8"            # mov rax,[rbp-8]             ; renderer
                       "8b88bc090000"        # mov ecx,[rax+0x9bc]
                       "488b84c810090000"    # mov rax,[rax+rcx*8+0x910]
                       "4885c0")             # test rax,rax
         + b"\x0f\x84" + rel32(0x12d2f7, CAVE)   # je cave
         + b"\x90\x90")
# cave: pRenderPassData = [rbp-0x18]; status [rbp-0x1c] is already 0
CAVE_NEW = (bytes.fromhex("488b45e8"         # mov rax,[rbp-0x18]
                          "c6400801"         # mov byte [rax+0x8],1     ; bCompNeeded
                          "c6402000")        # mov byte [rax+0x20],0    ; SFC-only output
            + b"\xe9" + rel32(CAVE + 17, 0x12d474))  # jmp epilogue

PATCHES = [
    ("A reporting ptr", 0x1336E8, A_OLD, A_NEW),
    ("B SetStatusReportParams", 0x130E80, B_OLD, B_NEW),
    ("C VEBOX dispatch", 0x12D2DC, C_OLD, C_NEW),
    ("C cave", CAVE, b"\x00" * len(CAVE_NEW), CAVE_NEW),
]


def main():
    src, dst = sys.argv[1], sys.argv[2]
    data = bytearray(open(src, "rb").read())
    sha = hashlib.sha256(data).hexdigest()
    if sha != ORIG_SHA256:
        sys.exit(f"unexpected input sha256 {sha}")
    for name, off, old, new in PATCHES:
        assert len(old) == len(new), (name, len(old), len(new))
        if data[off:off + len(old)] != old:
            sys.exit(f"{name}: bytes at {off:#x} do not match")
        data[off:off + len(new)] = new
        print(f"{name}: {len(new)} bytes at {off:#x}")
    open(dst, "wb").write(data)
    print(f"out sha256 {hashlib.sha256(data).hexdigest()}")


if __name__ == "__main__":
    main()
