#!/usr/bin/env python
"""Generate STEP bodies for the two parts no stock KiCad model covers.

Run with the cadquery venv (cadquery is not installed system-wide):

    ~/.venvs/cad/bin/python scripts/gen_3d_models.py

Writes into library/3d/ee.3dshapes/:

  YZV0004ADAD.step   U4, TPS22913B in TI's YZV DSBGA-4. Stock KiCad has no
                     4-ball DSBGA. Bump pitch 0.5 and body 0.93 square come
                     from our footprint (pads at +-0.25, courtyard +-0.465);
                     0.50 mm seated height as the shipped-board STEP export
                     used.
  LPR302823.step     BT1, the LiPol LPR302823 round pouch on its 3M VHB 4956
                     tape, as it sits on the BACK of the board. Not a PCB
                     part (BT1 is two wire pads); the model is there so the
                     3D view shows the real 4.7 mm stack.

Cell geometry follows design/parts/bt1-lipo-cell.md and
scripts/gen_lipo_fit_svg.py (nominal outline): Ø28, flat 9.0 mm from centre
(23 flat-to-far), flat square to the tip, centre 0.25 mm away from the tip,
cell 3.2 mm (CELL_T) on 1.5 mm tape (TAPE_T).

Frames: a KiCad model is y-UP while the footprint is y-down, so the
footprint's "centre at y=+0.25, flat toward -y (the tip)" becomes "centre at
y=-0.25, flat toward +y" here. z=0 is the seating plane (the back copper
face once KiCad flips the model onto B.Cu), +z points away from the board.
The wires are not modelled.
"""
import math
from pathlib import Path

import cadquery as cq

OUT = Path(__file__).resolve().parent.parent / "library" / "3d" / "ee.3dshapes"

# --- U4: DSBGA-4 -----------------------------------------------------------
BGA_BODY = 0.93
BGA_H = 0.50
BUMP_H = 0.17
BUMP_D = 0.25
BUMP_PITCH = 0.50

# --- BT1: LPR302823 on VHB --------------------------------------------------
CELL_R = 14.0      # Ø28
CELL_FLAT = 9.0    # flat chord distance from centre (23 - 14)
CELL_DY = 0.25     # centre offset away from the tip (footprint +y)
CELL_T = 3.2       # gen_lipo_fit_svg.CELL_T (vendor page; name implies 3.0)
TAPE_T = 1.5       # 3M VHB 4956


def dsbga4():
    die = (cq.Workplane("XY")
           .box(BGA_BODY, BGA_BODY, BGA_H - BUMP_H, centered=(True, True, False))
           .translate((0, 0, BUMP_H)))
    bumps = None
    for sx in (-1, 1):
        for sy in (-1, 1):
            b = (cq.Workplane("XY")
                 .cylinder(BUMP_H, BUMP_D / 2, centered=(True, True, False))
                 .translate((sx * BUMP_PITCH / 2, sy * BUMP_PITCH / 2, 0)))
            bumps = b if bumps is None else bumps.union(b)
    asm = cq.Assembly()
    asm.add(die, name="die", color=cq.Color(0.15, 0.15, 0.18))
    asm.add(bumps, name="bumps", color=cq.Color(0.80, 0.80, 0.82))
    return asm


def d_disc(z0, t):
    """Ø28 disc with the flat toward model +y, centre at y=-CELL_DY."""
    disc = cq.Workplane("XY").circle(CELL_R).extrude(t)
    keep = (cq.Workplane("XY")
            .rect(4 * CELL_R, 4 * CELL_R)
            .extrude(t)
            .translate((0, CELL_FLAT - 2 * CELL_R, 0)))
    return disc.intersect(keep).translate((0, -CELL_DY, z0))


def lipo():
    asm = cq.Assembly()
    asm.add(d_disc(0.0, TAPE_T), name="vhb_4956", color=cq.Color(0.55, 0.55, 0.58))
    cell = d_disc(TAPE_T, CELL_T).edges("not |Z").fillet(0.6)
    asm.add(cell, name="lpr302823", color=cq.Color(0.78, 0.79, 0.82))
    return asm


def report(asm, name):
    path = OUT / name
    asm.export(str(path))
    bb = asm.toCompound().BoundingBox()
    print(f"wrote {path.relative_to(OUT.parent.parent.parent)}  "
          f"x {bb.xmin:+.3f}..{bb.xmax:+.3f}  y {bb.ymin:+.3f}..{bb.ymax:+.3f}  "
          f"z {bb.zmin:+.3f}..{bb.zmax:+.3f}")


if __name__ == "__main__":
    report(dsbga4(), "YZV0004ADAD.step")
    report(lipo(), "LPR302823.step")
    # sanity: the flat sits 9.0 from the centre, so the chord half-width is
    print(f"chord half-width {math.sqrt(CELL_R**2 - CELL_FLAT**2):.2f} mm")
