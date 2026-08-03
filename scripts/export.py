#!/usr/bin/env python3
"""Export JLCPCB fabrication + assembly files.

out/jlcpcb/
  gerbers/…            individual layers + drill
  earring_gerbers.zip  upload this for the PCB
  bom.csv              JLC assembly BOM   (Comment,Designator,Footprint,LCSC)
  cpl.csv              JLC pick&place     (Designator,Mid X,Mid Y,Layer,Rotation)

Note: JLC rotations may need per-part correction after their DFM preview —
known quirk of their library orientations. Check the preview before ordering.
"""
import csv
import subprocess
import sys
import zipfile
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import build_circuit  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
OUT = ROOT / "out" / "jlcpcb"

LAYERS = ("F.Cu,In1.Cu,In2.Cu,B.Cu,F.Mask,B.Mask,F.Paste,B.Paste,"
          "F.Silkscreen,B.Silkscreen,Edge.Cuts")


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(" ".join(str(c) for c in cmd))
        print(r.stdout, r.stderr)
        sys.exit(1)


def main():
    gdir = OUT / "gerbers"
    gdir.mkdir(parents=True, exist_ok=True)
    for f in gdir.glob("*"):
        f.unlink()
    run(["kicad-cli", "pcb", "export", "gerbers", "--layers", LAYERS,
         "--subtract-soldermask", "-o", str(gdir) + "/", str(PCB)])
    run(["kicad-cli", "pcb", "export", "drill", "--format", "excellon",
         "--drill-origin", "absolute", "--excellon-units", "mm",
         "--generate-map", "--map-format", "gerberx2",
         "-o", str(gdir) + "/", str(PCB)])
    zpath = OUT / "earring_gerbers.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in sorted(gdir.glob("*")):
            z.write(f, f.name)
    print(f"wrote {zpath}")

    # --- BOM + CPL ---
    cir = build_circuit()
    board = pcbnew.LoadBoard(str(PCB))
    bom_rows = {}   # (value, footprint, lcsc) -> [refs]
    cpl_rows = []
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        comp = cir.components.get(ref)
        if comp is None or not comp.lcsc:
            continue  # testpoints etc: not assembled
        key = (comp.value, comp.footprint, comp.lcsc)
        bom_rows.setdefault(key, []).append(ref)
        pos = fp.GetPosition()
        cpl_rows.append([
            ref,
            f"{pcbnew.ToMM(pos.x):.3f}mm",
            f"{-pcbnew.ToMM(pos.y):.3f}mm",   # JLC wants +y up
            "bottom" if fp.GetLayer() == pcbnew.B_Cu else "top",
            f"{fp.GetOrientationDegrees():.1f}",
        ])
    with open(OUT / "bom.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
        for (val, fpname, lcsc), refs in sorted(bom_rows.items(), key=lambda kv: kv[1][0]):
            w.writerow([val, ",".join(sorted(refs)), fpname, lcsc])
    with open(OUT / "cpl.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        w.writerows(sorted(cpl_rows))
    n_parts = sum(len(r) for r in bom_rows.values())
    print(f"wrote bom.csv ({len(bom_rows)} lines) and cpl.csv ({n_parts} parts)")


if __name__ == "__main__":
    main()
