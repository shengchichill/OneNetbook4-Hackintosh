#!/bin/bash
# build.sh <real driver .bundle> <out dir>
# Builds vashim and assembles <out dir>/AppleIntelTGLGraphicsVADriver.bundle:
#   Contents/MacOS/AppleIntelTGLGraphicsVADriver       = vashim (exports AVD_Create/DestroyAVDAccelerator)
#   Contents/MacOS/AppleIntelTGLGraphicsVADriver.real  = the real driver from <real driver .bundle> (use the patch-tglva.py build)
#   Contents/MacOS/TGLVA, Info.plist, version.plist    = copied unchanged
# Everything ad-hoc signed. Install on the OneNetbook with: sudo tools/vabundle.sh install <out dir>/AppleIntelTGLGraphicsVADriver.bundle
set -euo pipefail
SRC=${1:?real driver bundle}
OUT=${2:?out dir}
HERE=$(cd "$(dirname "$0")" && pwd)
B=$OUT/AppleIntelTGLGraphicsVADriver.bundle
M=$B/Contents/MacOS
[ -e "$B" ] && { echo "$B exists; remove it first"; exit 1; }
mkdir -p "$OUT"
ditto "$SRC" "$B"
rm -rf "$B/Contents/_CodeSignature"
mv "$M/AppleIntelTGLGraphicsVADriver" "$M/AppleIntelTGLGraphicsVADriver.real"
clang -arch x86_64 -mmacosx-version-min=26.0 -O2 -Wall -Wextra -Wno-unused-parameter \
      -bundle -fvisibility=hidden -framework IOSurface -framework CoreFoundation -framework Accelerate \
      -o "$M/AppleIntelTGLGraphicsVADriver" "$HERE/vashim.c" "$HERE/swconvert.c"
codesign -f -s - "$M/TGLVA" "$M/AppleIntelTGLGraphicsVADriver.real"
codesign -f -s - "$B"
codesign -v --deep "$B" && echo "built $B"
nm -gU "$M/AppleIntelTGLGraphicsVADriver"
