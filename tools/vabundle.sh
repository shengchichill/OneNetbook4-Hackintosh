#!/bin/bash
# vabundle.sh install <patched .bundle dir> | disable | restore | status
# Swap /Library/GPUBundles/AppleIntelTGLGraphicsVADriver.bundle for the NULL-check patched build (tools/patch-tglva.py).
# The original is kept outside GPUBundles so nothing loads it by accident. No reboot needed (bundles load per process).
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
DEST=/Library/GPUBundles/AppleIntelTGLGraphicsVADriver.bundle
BAKDIR=/Users/Shared/onb4-backup
BAK=$BAKDIR/AppleIntelTGLGraphicsVADriver.bundle.orig
BIN=Contents/MacOS/AppleIntelTGLGraphicsVADriver

status() {
    [ -d "$DEST" ] || { echo "installed: (none — disabled)"; [ -d "$BAK" ] && echo "backup:    $(shasum -a 256 "$BAK/$BIN" | cut -d' ' -f1)"; return 0; }
    echo "installed: $(shasum -a 256 "$DEST/$BIN" | cut -d' ' -f1)"
    codesign -dvv "$DEST" 2>&1 | grep -E "^Authority|^Signature=" | head -2
    [ -d "$BAK" ] && echo "backup:    $(shasum -a 256 "$BAK/$BIN" | cut -d' ' -f1)" || echo "backup:    (none)"
}

case "${1:-status}" in
    status) status ;;
    install)
        [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
        NEW=${2:?patched bundle path}
        codesign -v "$NEW"
        mkdir -p "$BAKDIR"
        [ -d "$BAK" ] || ditto "$DEST" "$BAK"
        rm -rf "$DEST"
        ditto "$NEW" "$DEST"
        chown -R root:wheel "$DEST"
        status ;;
    disable)  # move the VA driver out of GPUBundles: VideoToolbox falls back to software decode/convert
        [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
        mkdir -p "$BAKDIR"
        [ -d "$BAK" ] || ditto "$DEST" "$BAK"
        rm -rf "$DEST"
        echo "VA driver removed from GPUBundles (original kept at $BAK)" ;;
    restore)
        [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
        [ -d "$BAK" ] || { echo "no backup at $BAK"; exit 1; }
        rm -rf "$DEST"
        ditto "$BAK" "$DEST"
        chown -R root:wheel "$DEST"
        status ;;
    *) echo "usage: $0 install <bundle>|disable|restore|status"; exit 2 ;;
esac
