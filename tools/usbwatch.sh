#!/bin/bash
# usbwatch.sh: print USB attach/detach events with port location and link speed, once per second.
# Run on macOS target: ssh host 'bash -s' -- SECONDS < tools/usbwatch.sh
dur=${1:-600}
snap() {
  ioreg -p IOUSB -l -w0 | awk '
    /\+-o / { if (name != "") print name " spd=" spd " ctrl=" ctrl
              line=$0; sub(/^.*\+-o /, "", line); split(line, a, "  <class ");
              name=a[1]; spd="?"; cls=a[2]; sub(/,.*/, "", cls)
              if (cls ~ /XHCI|AppleUSBHostController|^IORegistryEntry/) { if (cls !~ /Root|IORegistryEntry/) ctrl=name; name="" } }
    /"UsbLinkSpeed" = / { spd=$NF }
    END { if (name != "") print name " spd=" spd " ctrl=" ctrl }' | sort
}
prev=$(snap)
echo "$(date +%H:%M:%S) START"; echo "$prev" | sed 's/^/  present: /'
end=$(( $(date +%s) + dur ))
while [ "$(date +%s)" -lt "$end" ]; do
  sleep 1
  cur=$(snap)
  if [ "$cur" != "$prev" ]; then
    diff <(echo "$prev") <(echo "$cur") | grep '^[<>]' | sed -e "s/^>/$(date +%H:%M:%S) ATTACH/" -e "s/^</$(date +%H:%M:%S) DETACH/"
    prev=$cur
  fi
done
echo "$(date +%H:%M:%S) END"
