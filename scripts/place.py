#!/usr/bin/env python3
"""Placement: positions every footprint on the generated board.

Coordinate frame: board center = (100,100)mm sheet coords; +y is DOWN on
screen. "Screen angle" θ: pos = center + r·(cosθ, sinθ), so θ=90 is the
bottom of the board, θ=270 the top.

Layout:
  - USB-C at bottom edge (θ≈90), front
  - LED ring on front periphery, arc avoiding the USB connector
    LEDs rotated 45° (diamond) so DI/DO sit on the ring radius: the data
    chain routes as constant-radius arcs; VCC/GND pads land radially
    inward/outward for via drops to the inner planes.
  - RP2354A front center (rotated so USB pins face the connector)
  - Battery clip back center; BOOTSEL + testpoints on back annulus
"""
import math
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import build_circuit, load_design  # noqa: E402
from outline import led_path, geometry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
CX, CY = 100.0, 100.0


def mm(v):
    return pcbnew.FromMM(v)


def vec(x, y):
    """center-relative mm -> VECTOR2I"""
    return pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))


def polar(r, theta_deg):
    t = math.radians(theta_deg)
    return (r * math.cos(t), r * math.sin(t))


def place(fp, x, y, rot=0.0, back=False):
    fp.SetPosition(vec(x, y))
    if back and fp.GetLayer() != pcbnew.B_Cu:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetOrientationDegrees(rot)
    # keep reference text small & on fab layer conceptually; just shrink
    fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.5), mm(0.5)))
    fp.Reference().SetTextThickness(mm(0.1))
    fp.Reference().SetVisible(False)


def pad_pos(fp, num):
    for p in fp.Pads():
        if p.GetNumber() == str(num):
            return p.GetPosition()
    raise KeyError(num)


def main():
    design = load_design()
    cir = build_circuit(design)
    board = pcbnew.LoadBoard(str(PCB))
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    r_board = design["board"]["diameter_mm"] / 2
    r_led = r_board - design["leds"]["ring_margin_mm"]

    # ---------------- LED chain along the teardrop perimeter ----------------
    margin = design["leds"]["ring_margin_mm"]
    end_y = design["leds"].get("path_end_y", -13.2)
    path = led_path(design, margin, end_y)
    n = design["leds"]["count"]
    S = [i * path.length / (n - 1) for i in range(n)]
    pts = [path.point(si) for si in S]
    tangs = [path.tangent(si) for si in S]
    # pseudo polar angle matching the old circular convention
    pthetas = [math.degrees(math.atan2(t[1], t[0])) - 90 for t in tangs]

    best = None
    for k in range(4):
        for i in range(n):
            place(fps[f"LED{i+1}"], *pts[i], rot=(45.0 + 90.0 * k - pthetas[i]))
        total = 0.0
        for i in range(n - 1):
            a = pad_pos(fps[f"LED{i+1}"], 4)
            b = pad_pos(fps[f"LED{i+2}"], 1)
            total += math.hypot(a.x - b.x, a.y - b.y)
        if best is None or total < best[1]:
            best = (k, total)
    k = best[0]
    for i in range(n):
        place(fps[f"LED{i+1}"], *pts[i], rot=(45.0 + 90.0 * k - pthetas[i]))
    print(f"LED path: len={path.length:.1f}mm, orientation k={k}, "
          f"chain gap total {best[1]/1e6:.2f}mm")

    # bypass caps at every-2nd chain midpoint, shifted inward
    for i in range(n):
        ref = f"C{30+i}"
        if ref not in fps:
            continue
        sm = min(S[i] + path.length / (n - 1) / 2, path.length - 1)
        x, y = path.point(sm)
        nx, ny = path.normal_in(sm, design)
        t = path.tangent(sm)
        rot = -(math.degrees(math.atan2(t[1], t[0]))) 
        place(fps[ref], x + nx * 1.9, y + ny * 1.9, rot=rot)

    # ---------------- MCU + core cluster (front) ----------------
    place(fps["U1"], 0, -0.5, rot=180)  # USB pins (51/52) toward bottom
    # crystal above MCU (QFN courtyard reaches y=-4.62; keep clear)
    # Y1 rotated 180 so pad1 (XIN) sits on the right, under MCU pin 21 —
    # unrotated, XIN/XOUT arrive crossed and jam the crystal channel
    place(fps["Y1"], 0, -6.7, rot=180)
    place(fps["C14"], 2.4, -6.7, rot=90)   # XIN load cap, right
    place(fps["C15"], -4.05, -6.9, rot=90) # XTAL_R load cap, left
    place(fps["R1"], -2.4, -6.7, rot=90)   # XOUT series R beside crystal
    # VREG cluster bottom-left (VDD_CORE caps split: C12 near L1, C13 at
    # the DVDD pin on the other side of the QFN)
    place(fps["L1"], -3.9, 6.75, rot=0)
    place(fps["C11"], 2.6, -8.6, rot=0)
    place(fps["C12"], -5.9, -2.9, rot=90)  # near DVDD pin 39 (left column)
    place(fps["C13"], 3.1, -5.2, rot=0)
    # IOVDD decoupling: explicit pockets around the QFN courtyard (its
    # corners reach r≈6.2, so a uniform ring does not fit)
    DECAP = [(-4.8, -4.0, 90), (4.8, -3.9, 90),
             (-4.8, -2.0, 90), (4.8, -1.9, 90),
             (-4.8, 0.0, 90), (4.8, 0.1, 90),
             (4.8, 2.1, 90), (0, -9.3, 0),
             (-2.0, -9.6, 0), (-6.3, 5.7, 90)]
    for i, (x, y, rot) in enumerate(DECAP):
        place(fps[f"C{i+1}"], x, y, rot=rot)
    # RUN pullup + divider near left
    place(fps["R2"], -6.8, -4.8, rot=0)
    place(fps["R11"], -8.6, -1.2, rot=90)
    place(fps["R12"], -7.4, -1.2, rot=90)
    place(fps["C21"], -8.0, -3.0, rot=0)
    # BOOTSEL series R
    place(fps["R3"], 6.3, -6.1, rot=0)

    # ---------------- USB (back, at the teardrop tip) + charger ----------------
    og = geometry(design)
    overhang = design.get("usb", {}).get("overhang_mm", 1.3)
    j1_y = -og["tip_y"] + (5.21 - overhang)  # footprint +y extent = 5.21
    place(fps["J1"], 0, j1_y, rot=0, back=True)  # rot0: pads inboard, mouth out
    place(fps["R6"], -0.6, 4.6, rot=0)    # DP series R under pin 52
    place(fps["R7"], -1.0, 5.8, rot=0)    # DM series R below it
    # ESD chip beside the connector on the back
    place(fps["U5"], 5.7, -11.7, rot=0, back=True)
    place(fps["R4"], -2.5, -17.5, rot=90)  # CC pulldowns at the tip
    place(fps["R5"], 2.5, -17.5, rot=90)
    place(fps["U2"], 5.5, 5.0, rot=0)
    place(fps["R8"], 9.0, -0.9, rot=90)
    place(fps["C16"], 8.3, 3.9, rot=90)
    place(fps["C17"], 7.9, 0.7, rot=90)
    # charge LED + resistor: front upper-left interior
    place(fps["R9"], -7.7, -6.9, rot=90)
    place(fps["D1"], -6.2, -6.6, rot=90)

    # ---------------- power left/right (front) ----------------
    place(fps["U3"], -6.0, 3.2, rot=0)
    place(fps["C18"], -8.5, 1.2, rot=90)
    place(fps["C19"], -8.3, 3.6, rot=90)
    place(fps["U4"], 6.6, -1.6, rot=0)
    place(fps["R10"], 8.55, -2.0, rot=90)
    place(fps["C20"], 6.3, -3.8, rot=90)  # tight to U4 output

    # ---------------- hanger ----------------
    hx, hy = design.get("hanger", {}).get("pos", [0, -12.0])
    place(fps["H1"], hx, hy, rot=0)

    # ---------------- back side ----------------
    place(fps["BT1"], 0, 0, rot=0, back=True)  # feet at ±x
    # BOOTSEL: small top-actuated switch, front interior (the tip strip is
    # fully consumed by the USB shield legs + hanger)
    place(fps["SW1"], 1.9, 8.4, rot=0)
    # testpoints: back shoulders, clear of the battery insertion corridor
    # (|x|<10.5, y>9.7) and the clip feet
    for i, (x, y) in enumerate([(-11.8, -5.0), (11.8, -5.0), (-13.1, 4.9)]):
        place(fps[f"TP{i+1}"], x, y, back=True)

    resolve_overlaps(board, fps)
    pcbnew.SaveBoard(str(PCB), board)
    print(f"placed {len(fps)} footprints -> {PCB.name}")


def resolve_overlaps(board, fps, max_iter=300):
    """Relaxation pass: nudge small passives apart until no courtyard
    bboxes overlap. Ring caps (C30+) and non-passives stay fixed."""
    import re as _re

    EXEMPT = {"R4", "R5", "R8", "R9"}  # deliberately placed in the outer wedges

    def movable(ref):
        if ref in EXEMPT:
            return False
        m = _re.match(r"([RC])(\d+)$", ref)
        if not m:
            return False
        return not (m.group(1) == "C" and int(m.group(2)) >= 30)

    def cy_poly(fp):
        cy_layer = (pcbnew.B_CrtYd if fp.GetLayer() == pcbnew.B_Cu
                    else pcbnew.F_CrtYd)
        fp.BuildCourtyardCaches()  # positions changed since load
        sh = fp.GetCourtyard(cy_layer)
        if sh.OutlineCount() == 0:
            sh = pcbnew.SHAPE_POLY_SET()
            bb = fp.GetBoundingBox(False)
            sh.NewOutline()
            for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                         (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())):
                sh.Append(x, y)
        return sh

    def collide(fa, fb):
        pa, pb = cy_poly(fa), cy_poly(fb)
        if not pa.BBox().Intersects(pb.BBox()):
            return False
        inter = pcbnew.SHAPE_POLY_SET(pa)
        inter.BooleanIntersection(pb)
        return inter.OutlineCount() > 0

    def cy_bbox(fp):
        return cy_poly(fp).BBox()

    for it in range(max_iter):
        moved = False
        items = list(fps.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                ra, fa = items[i]
                rb, fb = items[j]
                if fa.GetLayer() != fb.GetLayer():
                    continue
                if not (movable(ra) or movable(rb)):
                    continue
                if not collide(fa, fb):
                    continue
                # push the movable one away from the other's center
                tgt, other = (fa, fb) if movable(ra) else (fb, fa)
                tp, op = tgt.GetPosition(), other.GetPosition()
                dx, dy = tp.x - op.x, tp.y - op.y
                norm = max(1, (dx * dx + dy * dy) ** 0.5)
                stepv = pcbnew.VECTOR2I(int(dx / norm * mm(0.15)),
                                        int(dy / norm * mm(0.15)))
                nx, ny = tp.x + stepv.x, tp.y + stepv.y
                # clamp movable passives to the center cluster (r <= 9.3mm):
                # beyond that lies the LED ring via band
                rx, ry = nx - mm(CX), ny - mm(CY)
                rr = (rx * rx + ry * ry) ** 0.5
                lim = mm(9.3)
                if rr > lim:
                    nx = mm(CX) + int(rx / rr * lim)
                    ny = mm(CY) + int(ry / rr * lim)
                tgt.SetPosition(pcbnew.VECTOR2I(int(nx), int(ny)))
                moved = True
        if not moved:
            if it:
                print(f"overlap relaxation converged after {it} iterations")
            return
    # report what is still colliding
    items = list(fps.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (ra, fa), (rb, fb) = items[i], items[j]
            if fa.GetLayer() != fb.GetLayer():
                continue
            if collide(fa, fb):
                print(f"  STILL OVERLAPPING: {ra} <-> {rb}")
    print("WARNING: overlap relaxation did not converge")


if __name__ == "__main__":
    main()
