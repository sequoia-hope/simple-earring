#!/usr/bin/env python3
"""Find legal placements for a footprint on the static board.

Every earlier attempt to eyeball a spot on this board failed the same way:
courtyards do NOT cover pad copper on SW2/SW1/U7/J1, and J1's tie pads are
custom pads whose GetSize() reports 0.01mm, so size-based reasoning sails
straight through real copper. This scanner works off actual pad polygons
(TransformShapeToPolygon), plus tracks, vias, holes, courtyards and the
board edge, and reports the spots that survive — ranked by how far the
part's own pads land from the pads they have to reach.

Usage:
  python3 tools/scan_spot.py REF [--side front|back|both] [--step 0.25]
                             [--rot 0,90,180,270] [--near REF.PAD,...]
                             [--clear 0.2] [--top 20] [--exclude REF,...]
                             [--keepout x0,y0,x1,y1;...]

The board is read as-is: run place.py and route.py --no-freeroute first, so
the locked pre-routes are present, and park the not-yet-placed parts
off-board so they are not scanned against themselves (--exclude them too).

NOTE the footprint is never moved during the sweep. Mutating a footprint
tens of thousands of times (SetPosition + BuildCourtyardCaches per probe)
segfaults KiCad 9.0.8. Instead each rotation's pad/courtyard polygons are
built once at the board centre and then translated as plain geometry.
"""
import argparse
import math
import sys
from pathlib import Path

import pcbnew

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
CX, CY = 100.0, 100.0
IU = 1e6  # nm per mm
ARC = int(0.005 * IU)
CU = (pcbnew.F_Cu, pcbnew.B_Cu)
CY_MARGIN = 0


def mm(v):
    return int(round(v * IU))


def bbox(ps):
    b = ps.BBox()
    return (b.GetLeft(), b.GetTop(), b.GetRight(), b.GetBottom())


def overlaps(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def poly_of(item, layer, clearance=0):
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, clearance, ARC, pcbnew.ERROR_OUTSIDE)
    return ps


def hole_poly(item, clearance):
    """Drill barrel + clearance, or None for a pad with no hole."""
    try:
        d = item.GetDrillSizeX() if hasattr(item, "GetDrillSizeX") else item.GetDrill()
    except Exception:
        return None
    if not d:
        return None
    p = item.GetPosition()
    ps = pcbnew.SHAPE_POLY_SET()
    ps.NewOutline()
    r = d / 2 + clearance
    for i in range(24):
        a = 2 * math.pi * i / 24
        ps.Append(int(p.x + r * math.cos(a)), int(p.y + r * math.sin(a)))
    return ps


def courtyard_of(fp):
    fp.BuildCourtyardCaches()
    lay = pcbnew.B_CrtYd if fp.GetLayer() == pcbnew.B_Cu else pcbnew.F_CrtYd
    cy = fp.GetCourtyard(lay)
    if cy.OutlineCount():
        return pcbnew.SHAPE_POLY_SET(cy)
    bb = fp.GetBoundingBox(False)
    ps = pcbnew.SHAPE_POLY_SET()
    ps.NewOutline()
    for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                 (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())):
        ps.Append(x, y)
    return ps


def intersects(a, b):
    i = pcbnew.SHAPE_POLY_SET(a)
    i.BooleanIntersection(b)
    return i.OutlineCount() > 0


class Static:
    """Everything already on the board, as polygons to collide against."""

    def __init__(self, board, skip, clear, hole_clear, edge_clear):
        self.copper = {pcbnew.F_Cu: [], pcbnew.B_Cu: []}
        self.cy = {pcbnew.F_Cu: [], pcbnew.B_Cu: []}
        self.holes = []
        for fp in board.GetFootprints():
            if fp.GetReference() in skip:
                continue
            c = courtyard_of(fp)
            self.cy[fp.GetLayer()].append((fp.GetReference(), bbox(c), c))
            for pad in fp.Pads():
                tag = f"{fp.GetReference()}.{pad.GetNumber()}"
                for lay in CU:
                    if pad.IsOnLayer(lay):
                        p = poly_of(pad, lay, clear)
                        self.copper[lay].append((tag, bbox(p), p))
                h = hole_poly(pad, hole_clear)
                if h is not None:
                    self.holes.append((tag + " drill", bbox(h), h))
        for t in board.GetTracks():
            tag = t.GetNetname() or "track"
            for lay in CU:
                if t.IsOnLayer(lay):
                    p = poly_of(t, lay, clear)
                    self.copper[lay].append((tag, bbox(p), p))
            if t.Type() == pcbnew.PCB_VIA_T:
                h = hole_poly(t, hole_clear)
                if h is not None:
                    self.holes.append((tag + " via drill", bbox(h), h))
        outline = pcbnew.SHAPE_POLY_SET()
        board.GetBoardPolygonOutlines(outline)
        self.inside = pcbnew.SHAPE_POLY_SET(outline)
        self.inside.Deflate(edge_clear, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                            ARC)

    def blocker(self, cy, cy_bb, pads, side, dx, dy):
        """First obstacle the candidate hits at this offset, or None.

        cy/pads are polygons built at the board centre; dx/dy are the
        integer-IU offsets to test at.
        """
        d = pcbnew.VECTOR2I(dx, dy)
        moved_bb = (cy_bb[0] + dx, cy_bb[1] + dy, cy_bb[2] + dx, cy_bb[3] + dy)
        for ref, bb, other in self.cy[side]:
            if overlaps(moved_bb, bb):
                m = pcbnew.SHAPE_POLY_SET(cy)
                m.Move(d)
                if intersects(m, other):
                    return f"courtyard {ref}"
        for lay, base_bb, base in pads:
            pb = (base_bb[0] + dx, base_bb[1] + dy,
                  base_bb[2] + dx, base_bb[3] + dy)
            mine = None
            for ref, bb, other in self.copper[lay]:
                if overlaps(pb, bb):
                    if mine is None:
                        mine = pcbnew.SHAPE_POLY_SET(base)
                        mine.Move(d)
                    if intersects(mine, other):
                        return f"copper {ref}"
            for ref, bb, other in self.holes:
                if overlaps(pb, bb):
                    if mine is None:
                        mine = pcbnew.SHAPE_POLY_SET(base)
                        mine.Move(d)
                    if intersects(mine, other):
                        return f"hole {ref}"
            if mine is None:
                mine = pcbnew.SHAPE_POLY_SET(base)
                mine.Move(d)
            out = pcbnew.SHAPE_POLY_SET(mine)
            out.BooleanSubtract(self.inside)
            if out.OutlineCount():
                return "board edge"
        return None


def shapes_for(fp, rot, back):
    """Pad + courtyard polygons for one (rotation, side), at board centre."""
    if (fp.GetLayer() == pcbnew.B_Cu) != back:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetPosition(pcbnew.VECTOR2I(mm(CX), mm(CY)))
    fp.SetOrientationDegrees(rot)
    cy = courtyard_of(fp)
    if CY_MARGIN:
        cy.Inflate(CY_MARGIN, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, ARC)
    pads = []
    for pad in fp.Pads():
        for lay in CU:
            if pad.IsOnLayer(lay):
                p = poly_of(pad, lay)
                pads.append((lay, bbox(p), p))
    return cy, bbox(cy), pads, fp.GetLayer()


def pad_xy(board, spec):
    ref, num = spec.split(".")
    fp = board.FindFootprintByReference(ref)
    if fp is None:
        raise SystemExit(f"no footprint {ref}")
    for p in fp.Pads():
        if p.GetNumber() == num:
            q = p.GetPosition()
            return q.x / IU - CX, q.y / IU - CY
    raise SystemExit(f"{ref} has no pad {num}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref")
    ap.add_argument("--side", default="both", choices=("front", "back", "both"))
    ap.add_argument("--step", type=float, default=0.25)
    ap.add_argument("--rot", default="0,90,180,270")
    ap.add_argument("--near", default="",
                    help="comma-separated REF.PAD the part should sit near")
    ap.add_argument("--clear", type=float, default=0.2)
    ap.add_argument("--hole-clear", type=float, default=0.3)
    ap.add_argument("--edge-clear", type=float, default=0.25)
    ap.add_argument("--cy-margin", type=float, default=0.0,
                    help="extra courtyard gap to demand — buy margin against "
                         "place.py's relaxer nudging a neighbour into the spot")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--exclude", default="")
    ap.add_argument("--keepout", default="",
                    help="x0,y0,x1,y1;... centre-relative boxes to avoid")
    ap.add_argument("--rmax", type=float, default=15.5)
    ap.add_argument("--board", default=str(PCB))
    a = ap.parse_args()

    board = pcbnew.LoadBoard(a.board)
    fp = board.FindFootprintByReference(a.ref)
    if fp is None:
        raise SystemExit(f"no footprint {a.ref}")
    skip = {a.ref} | {r for r in a.exclude.split(",") if r}
    targets = [pad_xy(board, s) for s in a.near.split(",") if s]
    keepouts = []
    for box in a.keepout.split(";"):
        if box:
            x0, y0, x1, y1 = (float(v) for v in box.split(","))
            keepouts.append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))

    global CY_MARGIN
    CY_MARGIN = mm(a.cy_margin)
    static = Static(board, skip, mm(a.clear), mm(a.hole_clear), mm(a.edge_clear))
    rots = [float(r) for r in a.rot.split(",")]
    sides = {"front": [False], "back": [True], "both": [False, True]}[a.side]

    results, tried = [], 0
    n = int(2 * a.rmax / a.step) + 1
    for back in sides:
        for rot in rots:
            cy, cy_bb, pads, side = shapes_for(fp, rot, back)
            for i in range(n):
                x = -a.rmax + i * a.step
                for j in range(n):
                    y = -a.rmax + j * a.step
                    if math.hypot(x, y) > a.rmax:
                        continue
                    if any(k[0] <= x <= k[2] and k[1] <= y <= k[3]
                           for k in keepouts):
                        continue
                    tried += 1
                    if static.blocker(cy, cy_bb, pads, side,
                                      mm(x), mm(y)) is None:
                        score = sum(math.hypot(x - tx, y - ty)
                                    for tx, ty in targets)
                        results.append((score, x, y, rot, back))

    results.sort(key=lambda r: (r[0], abs(r[1]) + abs(r[2])))
    print(f"{a.ref}: {len(results)} legal of {tried} tried "
          f"(step {a.step}mm, clearance {a.clear}mm)")
    for score, x, y, rot, back in results[:a.top]:
        near = f"  sum-dist {score:6.2f}" if targets else ""
        print(f"  ({x:7.2f}, {y:7.2f}) rot {rot:5.1f} "
              f"{'back' if back else 'front'}{near}")
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
