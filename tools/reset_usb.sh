#!/usr/bin/env bash
# reset_usb.sh — restart the host xhci controller the earring flashes through.
#
# Unbinds + rebinds one xhci PCI function, which power-cycles every port on
# it (keyboard/mouse on the same controller blip for ~2s — that's why the
# whole sequence runs inside one script: you can't type mid-way).
#
# Usage:
#   tools/reset_usb.sh              # auto-detect (RP2350's bus, else 0d:00.4)
#   tools/reset_usb.sh 0000:0d:00.4 # explicit PCI function
#   FORCE=1 tools/reset_usb.sh ...  # skip the mounted-disk safety check
set -euo pipefail

DEFAULT_CTRL="0000:0d:00.4"   # the controller the earring's port is on (Aug 2026)

if [ "$(id -u)" -ne 0 ]; then
  exec sudo FORCE="${FORCE:-}" "$0" "$@"
fi

ctrl="${1:-}"
if [ -z "$ctrl" ]; then
  # prefer the controller currently hosting an RP2350 (2e8a:*)
  for dev in /sys/bus/usb/devices/*/idVendor; do
    if [ "$(cat "$dev" 2>/dev/null)" = "2e8a" ]; then
      path=$(readlink -f "$(dirname "$dev")")
      ctrl=$(echo "$path" | grep -oE '0000:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9]' | tail -1)
      break
    fi
  done
  ctrl="${ctrl:-$DEFAULT_CTRL}"
fi

drv="/sys/bus/pci/drivers/xhci_hcd"
[ -e "$drv/$ctrl" ] || { echo "ERROR: $ctrl is not bound to xhci_hcd"; exit 1; }

# safety: refuse if a MOUNTED block device hangs off this controller
if [ -z "${FORCE:-}" ]; then
  for blk in /sys/block/*; do
    dev=$(basename "$blk")
    case "$(readlink -f "$blk")" in
      *"$ctrl"*)
        if grep -q "^/dev/$dev" /proc/mounts; then
          echo "ERROR: /dev/$dev is mounted and sits on $ctrl — unmount it or FORCE=1"
          exit 1
        fi ;;
    esac
  done
fi

buses=$(for b in /sys/bus/usb/devices/usb*; do
          case "$(readlink -f "$b")" in *"$ctrl"*) basename "$b";; esac
        done | tr '\n' ' ')
echo "restarting xhci controller $ctrl (buses: ${buses:-?})"

echo "$ctrl" > "$drv/unbind"
sleep 2
echo "$ctrl" > "$drv/bind"

# wait for the root hubs to come back
for _ in $(seq 20); do
  [ -e "/sys/bus/pci/drivers/xhci_hcd/$ctrl" ] && break
  sleep 0.5
done
sleep 1
echo "controller back; current devices on its buses:"
for b in $buses; do lsusb -s "${b#usb}:" 2>/dev/null; done
echo "done"
