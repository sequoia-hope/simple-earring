#!/usr/bin/env python3
"""Render top/bottom PNGs of the board for visual review."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"


def main():
    ok = True
    for side in ("top", "bottom"):
        out = ROOT / "out" / f"render_{side}.png"
        r = subprocess.run(
            ["kicad-cli", "pcb", "render", "--side", side,
             "--quality", "high", "--zoom", "0.9",
             "-o", str(out), str(PCB)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            print(f"wrote {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
