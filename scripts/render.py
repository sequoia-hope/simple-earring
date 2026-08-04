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
    # --placement: quick post-place preview (no routing yet) -> separate
    # files so the routed renders aren't clobbered mid-build
    placement = "--placement" in sys.argv
    prefix = "render_place_" if placement else "render_"
    for side in ("top", "bottom"):
        out = ROOT / "out" / f"{prefix}{side}.png"
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
    if placement:
        sys.exit(0 if ok else 1)
    # layout views: kicad-cli only exports vector formats for layer views,
    # so export SVG then rasterize to a PNG matching the 3D render size
    # (board centered on white); the intermediate SVG is removed
    try:
        from PIL import Image
        size = Image.open(ROOT / "out" / f"{prefix}top.png").size
    except Exception:
        size = (1568, 872)
    for side, (layers, mirror) in LAYOUT_VIEWS.items():
        svg = ROOT / "out" / f"layout_{side}.svg"
        cmd = ["kicad-cli", "pcb", "export", "svg", "--mode-single",
               "--layers", layers, "--page-size-mode", "2",
               "--exclude-drawing-sheet", "-o", str(svg), str(PCB)]
        if mirror:
            cmd.insert(cmd.index("-o"), "--mirror")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
            continue
        out = ROOT / "out" / f"layout_{side}.png"
        wh = f"{size[0]}x{size[1]}"
        r = subprocess.run(
            ["magick", "-density", "600", "-background", "white",
             str(svg), "-resize", wh, "-gravity", "center",
             "-extent", wh, "-alpha", "remove", "-alpha", "off",
             "-depth", "8", str(out)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            svg.unlink()
            print(f"wrote {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
