#!/bin/bash
# gvascaler.sh off|gva-off|on|status — toggle GVA keys in the WhateverXe-Graphics AppleIntelTGLGraphics.kext.
# Why: with IOGVAScaler=Gen10, AppleGVA routes VTPixelTransferSession (scale / color convert) to the old
# Apple TGL VA driver, which segfaults (WebKit.GPU drawVideoFrame) or hangs the GPU in a MEDIA_OBJECT kernel.
# off: back up Info.plist, delete IOGVAScaler from every personality, rebuild the aux KC (same as the pkg postinstall).
# gva-off: delete every IOGVA* key and IODVDBundleName, so VideoToolbox / AVFoundation / WindowServer
#      see no hardware video at all and use software paths. Needed while the VA bundle is disabled:
#      with the keys still there, WindowServer asserts in AppleGVACore (GVAInstance::transfer_image_async)
#      and VTDecoderXPCService fails with -12900 (Apple Music video, 2026-11-06).
# on : restore the backup and rebuild. Needs root; reboot afterwards.
set -euo pipefail
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
KEXT=/Library/Extensions/AppleIntelTGLGraphics.kext
P=$KEXT/Contents/Info.plist
BAK=/Library/Extensions/.onb4-AppleIntelTGLGraphics-Info.plist.orig
PB=/usr/libexec/PlistBuddy

personalities() { "$PB" -c "Print :IOKitPersonalities" "$P" | awk '/^    [A-Za-z0-9_]+ = Dict/{print $1}'; }
gvakeys() { "$PB" -c "Print :IOKitPersonalities:$1" "$P" | awk '/^    (IOGVA[A-Za-z0-9]*|IODVDBundleName) = /{print $1}'; }
status() { for n in $(personalities); do echo "$n: $(gvakeys "$n" | tr '\n' ' ')"; done; }

rebuild_auxkc() {
    local work kext
    work=$(mktemp -d /Library/KernelCollections/.onb4.XXXXXX)
    local args=(create -n aux -x -z -V release -r /Library/Extensions --allow-missing-kdk)
    for kext in /Library/Extensions/*.kext; do [ -d "$kext" ] && args+=(-p "$kext"); done
    kmutil "${args[@]}" \
        -B /System/Library/KernelCollections/BootKernelExtensions.kc \
        -S /System/Library/KernelCollections/SystemKernelExtensions.kc \
        -A "$work/AuxiliaryKernelExtensions.kc" --no-authentication
    chmod 0644 "$work/AuxiliaryKernelExtensions.kc"
    mv -f "$work/AuxiliaryKernelExtensions.kc" /Library/KernelCollections/AuxiliaryKernelExtensions.kc
    rmdir "$work"
    echo "aux KC rebuilt: $(ls -l /Library/KernelCollections/AuxiliaryKernelExtensions.kc)"
}

case "${1:-status}" in
    status) status ;;
    off)
        [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
        [ -f "$BAK" ] || cp -p "$P" "$BAK"
        echo "backup: $BAK"
        for n in $(personalities); do "$PB" -c "Delete :IOKitPersonalities:$n:IOGVAScaler" "$P" 2>/dev/null || true; done
        status; rebuild_auxkc; echo "done — reboot to apply" ;;
    gva-off)
        [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
        [ -f "$BAK" ] || cp -p "$P" "$BAK"
        echo "backup: $BAK"
        for n in $(personalities); do for k in $(gvakeys "$n"); do "$PB" -c "Delete :IOKitPersonalities:$n:$k" "$P"; done; done
        status; rebuild_auxkc; echo "done — reboot to apply" ;;
    on)
        [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
        [ -f "$BAK" ] || { echo "no backup at $BAK"; exit 1; }
        cp -p "$BAK" "$P"
        status; rebuild_auxkc; echo "done — reboot to apply" ;;
    *) echo "usage: $0 off|gva-off|on|status"; exit 2 ;;
esac
