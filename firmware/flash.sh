#!/usr/bin/env bash
# flash.sh — build and flash the latest earring firmware.
#
# Works from either board state:
#   - app running (2e8a:f00f, /dev/ttyACM*): auto-resets via 1200-baud touch
#   - bootloader   (2e8a:000f):              flashes directly via picotool
# If no board is present, waits up to WAIT seconds for one to appear.
#
# Remember: with a battery fitted, replugging USB does NOT reset the chip.
# To force the bootloader on a bricked/erased board: SW2 OFF, hold
# BOOTSEL, SW2 ON.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

WAIT="${WAIT:-60}"

if ! lsusb | grep -q "2e8a:"; then
  echo "no board on USB — waiting up to ${WAIT}s (plug it in)..."
  for _ in $(seq "$WAIT"); do
    lsusb | grep -q "2e8a:" && break
    sleep 1
  done
  lsusb | grep -q "2e8a:" || { echo "no board appeared, giving up"; exit 1; }
fi
lsusb | grep "2e8a:"

pio run -t upload

echo "waiting for the app to come back..."
for _ in $(seq 15); do
  if ls /dev/ttyACM* >/dev/null 2>&1; then
    echo "up: $(ls /dev/ttyACM*)"
    exit 0
  fi
  sleep 1
done
echo "flashed OK but no CDC port appeared — power cycle via SW2 if dark"
exit 1
