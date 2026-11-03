#!/usr/bin/env bash
# view.sh -- run pcbview, the board viewer generator, from the pinned submodule.
#
#     scripts/view.sh build pcbview.toml          every board in the config
#     scripts/view.sh models pcbview.toml         which parts lack a 3D model
#
# Set $PCBVIEW to use another checkout's bin/pcbview instead.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pcbview="${PCBVIEW:-$root/vendor/pcbview/bin/pcbview}"

if [[ ! -x "$pcbview" ]]; then
  echo "view.sh: pcbview not found at $pcbview" >&2
  echo "         run: git submodule update --init" >&2
  exit 1
fi

# A fresh project has no boards yet; say so instead of pcbview's terse error.
if [[ "${1:-}" == build && -f "${2:-}" ]] && ! grep -q '^\[\[boards\]\]' "$2"; then
  echo "view.sh: $2 has no [[boards]] yet. Add one when the first KiCad project exists under hw/." >&2
  exit 1
fi

exec "$pcbview" "$@"
