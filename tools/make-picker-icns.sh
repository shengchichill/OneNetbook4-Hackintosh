#!/bin/bash
# 產生 OpenCanopy 選單用的 Apple.icns（macOS 項目）與 Fedora.icns（Fedora 項目），2026-11-20。
# 兩個都是「純 logo」：不加底板或硬碟。OpenCore 依 flavour 找圖示：macOS 自動項目預設 flavour Apple → Apple.icns，
# Fedora 項目（config Flavour Fedora:Linux）→ Fedora.icns；找不到就退回 HardDrive.icns。
# Apple 用銀色漸層（不用純白）：選取框是淺色方塊，純白 logo 在上面看不清楚。
# 來源 SVG：resources/picker/fedora-icon-2021.svg（Wikimedia "Fedora icon (2021)"）、
#           resources/picker/apple-logo.svg（Wikimedia "Apple logo black"）。
# 需要 ImageMagick（magick）。輸出 ic07 128px + ic13 256px，與主題原圖相同結構。
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
R=$ROOT/resources/picker
T=$(mktemp -d); trap 'rm -r "$T"' EXIT
cd "$T"

pack() {  # pack <128.png> <256.png> <out.icns>
  python3 -I - "$1" "$2" "$3" <<'EOF'
import sys, struct
a = open(sys.argv[1], 'rb').read(); b = open(sys.argv[2], 'rb').read()
body = b''.join(struct.pack('>4sI', t, len(d) + 8) + d for t, d in ((b'ic07', a), (b'ic13', b)))
open(sys.argv[3], 'wb').write(b'icns' + struct.pack('>I', len(body) + 8) + body)
EOF
}

# Fedora：官方藍底白 f，佔畫布約 77%
magick -background none -density 400 "$R/fedora-icon-2021.svg" -resize 512x512 fedora512.png
for s in 256 128; do
  l=$(( s * 196 / 256 ))
  magick fedora512.png -resize ${l}x${l} -background none -gravity center -extent ${s}x${s} -strip PNG32:fedora$s.png
done
pack fedora128.png fedora256.png "$R/Fedora.icns"

# Apple：黑色 logo 當遮罩，填銀色垂直漸層，高約畫布 73%
for s in 256 128; do
  h=$(( s * 188 / 256 ))
  magick -background none -density 600 "$R/apple-logo.svg" -resize x$h mask$s.png
  w=$(magick mask$s.png -format %w info:)
  magick -size ${w}x${h} gradient:'#f4f4f7'-'#9c9ca3' \( mask$s.png -alpha extract \) -alpha off -compose copy_opacity -composite fill$s.png
  magick -size ${s}x${s} xc:none fill$s.png -gravity center -geometry +0-$(( s / 64 )) -compose over -composite -strip PNG32:apple$s.png
done
pack apple128.png apple256.png "$R/Apple.icns"
echo "wrote $R/Fedora.icns $R/Apple.icns"
