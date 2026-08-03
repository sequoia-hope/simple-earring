#!/usr/bin/env python3
"""Render top/bottom PNGs (3D raytrace) and layout-view SVGs (2D, PCB
editor look: viewed side's copper frontmost, other layers behind) of the
board for visual review."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"

# layers listed back-to-front; kicad-cli draws them in list order
LAYOUT_VIEWS = {
    "top": ("B.Cu,In2.Cu,In1.Cu,F.Cu,F.Silkscreen,Edge.Cuts", False),
    "bottom": ("F.Cu,In1.Cu,In2.Cu,B.Cu,B.Silkscreen,Edge.Cuts", True),
}


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
    for side, (layers, mirror) in LAYOUT_VIEWS.items():
        out = ROOT / "out" / f"layout_{side}.svg"
        cmd = ["kicad-cli", "pcb", "export", "svg", "--mode-single",
               "--layers", layers, "--page-size-mode", "2",
               "--exclude-drawing-sheet", "-o", str(out), str(PCB)]
        if mirror:
            cmd.insert(cmd.index("-o"), "--mirror")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            print(f"wrote {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
