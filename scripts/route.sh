#!/usr/bin/env bash
# route.sh -- run ultraroute, the autorouter, from the pinned submodule.
#
#     scripts/route.sh route board.kicad_pcb -o out.kicad_pcb [options]   (ultraroute's own CLI)
#     scripts/route.sh --build                                           build only, print the binary
#
# The first run builds vendor/ultraroute/core with cargo into build/ultraroute
# (needs Rust); later runs rebuild only when the submodule moves. Set
# $ULTRAROUTE to use another checkout's binary instead. Routing is normally
# driven by the skill's autoroute.py, which governs the run; call this
# directly only to try options by hand.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
core="$root/vendor/ultraroute/core"

if [[ -n "${ULTRAROUTE:-}" ]]; then
  bin="$ULTRAROUTE"
else
  if [[ ! -f "$core/Cargo.toml" ]]; then
    echo "route.sh: ultraroute not found at $core" >&2
    echo "          run: git submodule update --init" >&2
    exit 1
  fi
  target="$root/build/ultraroute"
  bin="$target/release/ultraroute"
  pinned="$(git -C "$root/vendor/ultraroute" rev-parse HEAD)"
  if [[ ! -x "$bin" || "$(cat "$target/.built-from" 2>/dev/null)" != "$pinned" ]]; then
    if ! command -v cargo >/dev/null; then
      echo "route.sh: cargo not found; install Rust (https://rustup.rs) to build ultraroute" >&2
      exit 1
    fi
    echo "route.sh: building ultraroute ${pinned:0:7} (once per pin)" >&2
    (cd "$core" && CARGO_TARGET_DIR="$target" nice -n 15 cargo build --release --quiet -p ultraroute >&2)
    echo "$pinned" > "$target/.built-from"
  fi
fi

if [[ "${1:-}" == --build ]]; then
  echo "$bin"
  exit 0
fi
exec "$bin" "$@"
