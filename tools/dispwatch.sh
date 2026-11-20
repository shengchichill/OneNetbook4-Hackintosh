#!/bin/bash
# dispwatch.sh: watch framebuffer connection state + USB devices + kernel display/hotplug log while plugging monitors.
# Run on macOS target: ssh host 'bash -s' -- SECONDS < tools/dispwatch.sh
dur=${1:-600}
fb() {
  ioreg -lw0 -c AppleIntelFramebuffer | awk '
    /\+-o AppleIntelFramebuffer@/ { if (n != "") print n, pc, ct, pn; n=$0; sub(/^.*\+-o /, "", n); sub(/ .*/, "", n); pc="pix=-"; ct="conn=-"; pn="" }
    /"IOFBCurrentPixelCount" =/ { pc="pix=" $NF }
    /"connector-type" =/ { ct="conn=" $NF }
    /"port-number" =/ { pn="port=" $NF }
    END { if (n != "") print n, pc, ct, pn }'
  echo "displays=$(ioreg -lw0 -c AppleDisplay | grep -c '+-o AppleDisplay')"
}
usb() {
  ioreg -p IOUSB -l -w0 | awk '
    /\+-o / { if (name != "") print "usb " name " spd=" spd; line=$0; sub(/^.*\+-o /, "", line); split(line, a, "  <class ");
              name=a[1]; spd="?"; cls=a[2]; sub(/,.*/, "", cls); if (cls !~ /IOUSBHostDevice/) name="" }
    /"UsbLinkSpeed" = / { spd=$NF }
    END { if (name != "") print "usb " name " spd=" spd }' | sort
}
snap() { fb; usb; }
/usr/bin/log stream --style compact --predicate 'process == "kernel" AND (eventMessage CONTAINS[c] "hotplug" OR eventMessage CONTAINS[c] "HPD" OR eventMessage CONTAINS[c] "AppleIntelFramebuffer" OR eventMessage CONTAINS "TGL" OR eventMessage CONTAINS[c] "WhateverXe" OR eventMessage CONTAINS[c] "typec" OR eventMessage CONTAINS[c] "Type-C" OR eventMessage CONTAINS[c] "IOFramebuffer" OR eventMessage CONTAINS[c] "AppleDisplay" OR eventMessage CONTAINS[c] "IOM")' 2>&1 | sed -u 's/^/LOG /' | cut -c1-260 &
lp=$!
prev=$(snap)
echo "$(date +%H:%M:%S) START"; echo "$prev" | sed 's/^/  present: /'
end=$(( $(date +%s) + dur ))
while [ "$(date +%s)" -lt "$end" ]; do
  sleep 2
  cur=$(snap)
  if [ "$cur" != "$prev" ]; then
    diff <(echo "$prev") <(echo "$cur") | grep '^[<>]' | sed -e "s/^>/$(date +%H:%M:%S) NEW /" -e "s/^</$(date +%H:%M:%S) GONE/"
    prev=$cur
  fi
done
kill $lp 2>/dev/null
pkill -u "$(id -u)" -f '^/usr/bin/log stream --style compact --predicate process == "kernel" AND \(eventMessage CONTAINS\[c\] "hotplug"' 2>/dev/null
echo "$(date +%H:%M:%S) END"
