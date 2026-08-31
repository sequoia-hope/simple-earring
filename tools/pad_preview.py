#!/usr/bin/env python3
"""Show where a footprint's pads land for a candidate placement.

Rotation sense is NEGATED on the back side (a front-frame angle θ becomes
180−θ), so the only safe way to pick an orientation is to place it and read
the pads back. Usage:

  python3 tools/pad_preview.py Q2 9.25 8.0 --rot 0,90,180,270 --back
"""
import argparse
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
CX, CY = 100.0, 100.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("x", type=float)
    ap.add_argument("y", type=float)
    ap.add_argument("--rot", default="0,90,180,270")
    ap.add_argument("--back", action="store_true")
    ap.add_argument("--board", default=str(PCB))
    a = ap.parse_args()

    board = pcbnew.LoadBoard(a.board)
    fp = board.FindFootprintByReference(a.ref)
    if fp is None:
        raise SystemExit(f"no footprint {a.ref}")
    if (fp.GetLayer() == pcbnew.B_Cu) != a.back:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    for rot in (float(r) for r in a.rot.split(",")):
        fp.SetPosition(pcbnew.VECTOR2I(int((CX + a.x) * 1e6),
                                       int((CY + a.y) * 1e6)))
        fp.SetOrientationDegrees(rot)
        bits = []
        for p in fp.Pads():
            q = p.GetPosition()
            bits.append(f"{p.GetNumber()}:({q.x/1e6-CX:6.2f},{q.y/1e6-CY:6.2f})"
                        f" {p.GetNetname() or '-'}")
        print(f"rot {rot:5.1f} {'back' if a.back else 'front'}  " + "  ".join(bits))


if __name__ == "__main__":
    main()
