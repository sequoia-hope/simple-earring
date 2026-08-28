#!/usr/bin/env python3
"""TPU clip-on case for the simple_earring board — two interlocking halves.

FRONT half : light-guide diffuser.  A pocket above every LED concentrates that
             LED onto a smooth, flat outer face.
REAR  half : closed cup over the coin cell + holder — the short-protection half.

Each half locks to the BOARD only — there is no half-to-half catch and nothing
sticks out.  The rim is divided into stations that alternate FRONT / REAR
ownership; at its own stations a half sends a finger past the board mid-plane,
wraps the PCB edge and catches a flat lip on the *opposite* board face.  The
mating half is simply cut away there, so the two rims interleave as a plain
castellation that keeps them aligned and leaves a flush outer surface.  Same
pattern on both halves, offset by one station.

SW2 lives in an open thumb scoop bitten out of both rims on the left flank.

Both halves print flat-face-down with no supports: every cavity opens upward.

Geometry comes from the ORDERED board revision (the hardware that exists), not
from the working tree — see BOARD_REV.

    python3 scripts/gen_case.py               # -> out/case/*.step, *.stl
    python3 scripts/gen_case.py --bat 4.5     # if the measured stack differs

Coordinates: board centre at the origin, +x right, +y toward the USB tip
(KiCad's +y is flipped), z = 0 on the FRONT copper face, z = -T_PCB on the back.
"""
import argparse
import math
import re
import subprocess
from pathlib import Path

import cadquery as cq
from cadquery import Vector
from cadquery.occ_impl.shapes import Edge, Wire

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "case"

# The revision that was fabricated.  The working tree has moved on (rev 2) but
# the case has to fit the board that exists.
BOARD_REV = "43eadc1"
BOARD_PATH_IN_REV = "out/earring.kicad_pcb"
KICAD_ORIGIN = (100.0, 100.0)

# ---------------------------------------------------------------- parameters
T_PCB = 1.60            # board thickness
SEAM_Z = -T_PCB / 2     # the halves meet at the board mid-plane

WALL = 1.80             # rim wall, radial
EDGE_GAP = 0.10         # wall inner face vs board edge (TPU closes this)
FINGER_T = WALL - EDGE_GAP   # fingers fill the wall -> flush outer surface
STATION_W = 4.00        # finger width along the rim
STATION_GAP = 0.15      # slot clearance around a finger

CHAMFER = 1.00          # roll-over at each outer face: this much radially...
CHAMFER_H = 1.40        # ...over this much height (~54 deg, clear of 45)

# --- front half
F_TOP = 3.45            # outer face (flat -> prints face-down on the bed)
F_FLOOR_RING = 1.05     # inner floor over the LED ring
F_FLOOR_MID = 1.60      # inner floor over the MCU cluster
RING_BAND = 4.00        # "ring zone" = within this of the board edge
POCKET_TOP = 2.35       # LED pocket ceiling -> 1.10 mm of diffuser skin
POCKET_R0 = 1.00        # pocket radius at the mouth (board side)
POCKET_R1 = 0.62        # ... and at the ceiling
LED_BOSS_R = 1.70       # boss dropping the mid-zone floor to F_FLOOR_RING
F_LEDGE = 0.85          # seat ledge on the front face, inboard from the edge
F_LIP = 1.00            # finger lip reach onto the BACK face
F_LIP_END = -T_PCB - 0.70    # bottom of the flat lip
F_FINGER_Z = -T_PCB - 1.40   # finger tip (lead-in ramp between the two)
F_WALL_YMAX = 19.0      # no front rim above this (mount-plug clearance)
F_CLIP_Y = 21.0         # front half clipped here

# --- rear half
R_SHELL = 1.20          # cup floor / outer wall thickness
R_FLOOR_GAP = 0.35      # clearance over the battery stack
R_LEDGE = 0.70          # seat ledge on the back face
R_LIP = 0.80            # finger lip reach onto the FRONT face
R_LIP_END = 0.55        # top of the flat lip
R_FINGER_Z = 1.05       # finger tip (== front floor, so the slot is clean)
R_CLIP_Y = 14.6         # rear half clipped here (USB body starts at y 14.33)
CELL_PAD_R = 6.50       # soft pad backing the coin cell up

# SW2 thumb scoop.  The knob already pokes 1.25 mm past the board edge and
# slides ALONG the left flank, so the affordance is an open scallop bitten out
# of both rims there: from NOTCH_Y0 on the round part up to where the left tip
# hook starts, floor at NOTCH_Z, raked back at the bottom so it prints clean.
NOTCH_Y0 = 5.50
NOTCH_Z = -4.60
NOTCH_RAKE = 3.00

KEEPOUT_XY = 0.30       # courtyard grow
KEEPOUT_Z = 0.20

# Station centres, CAD degrees.  FRONT stations wrap onto the BACK face, so
# they must sit where the back is clear near the edge; REAR stations wrap onto
# the FRONT face (only the LED ring is there, 1.22 mm in, all the way round).
# --report prints the measured margin for every one of them.
STATIONS = [
    (195.0, "rear"), (232.0, "front"), (252.0, "rear"), (272.0, "front"),
    (292.0, "rear"), (312.0, "front"), (332.0, "rear"), (25.0, "front"),
]
TIP_HOOK_Y = 17.0       # extra front-only hooks on the straight tip flanks

# part height above its own board face, by footprint-name fragment
HEIGHTS = [
    ("LED_SK6805", 0.60), ("LED_TBA", 0.60),
    ("C_0402", 0.55), ("R_0402", 0.55),
    ("C_0603", 0.95), ("C_0805", 1.05),
    ("L_pol_2016", 1.05), ("Crystal_SMD_3225", 0.85),
    ("RP2350-QFN-60", 0.90), ("WDFN-6-2x2", 0.70),
    ("DFN-8-1EP", 0.80), ("YZV0004", 0.60),
    ("USON-8", 0.60), ("SOT-666", 0.65), ("SOT-323", 1.20),
    ("LGA-14", 0.95), ("TestPoint_Pad", 0.10),
    ("KEY-SMD_4P", 2.55), ("SW-TH_MSK12C02", 1.60),
    ("USB-C_SMD", 3.35), ("BAT_CR2032", 5.10), ("BAT_MY2032", 3.70),
    ("SENSOR_ALS", 0.60),
]
# The battery courtyard is only the clip feet, so BT1 gets a hand-built
# envelope instead: the cell + holder ring (a disc, from the vendor 3D model,
# rmax 10.58) union the clip arms and their pads (a slab out to the courtyard).
BAT_REF = "BT1"
BAT_CELL_R = 10.75
BAT_ARM = (14.10, 3.40, 1.70)   # half-x, half-y, height


# ------------------------------------------------------------ board scraping
def sexp_blocks(s, tag):
    """Top-level `(tag ...)` blocks in a KiCad s-expression string."""
    out, i, pat = [], 0, "(" + tag
    while True:
        i = s.find(pat, i)
        if i < 0:
            return out
        if i + len(pat) >= len(s) or s[i + len(pat)] not in " \n\t":
            i += len(pat)
            continue
        d, j = 0, i
        while j < len(s):
            c = s[j]
            if c == '"':
                j += 1
                while j < len(s) and (s[j] != '"' or s[j - 1] == "\\"):
                    j += 1
            elif c == "(":
                d += 1
            elif c == ")":
                d -= 1
                if d == 0:
                    break
            j += 1
        out.append(s[i:j + 1])
        i = j + 1


def part_height(fp_name):
    for frag, h in HEIGHTS:
        if frag in fp_name:
            return h
    return 1.00


def read_board(path=None):
    if path:
        txt = Path(path).read_text()
    else:
        txt = subprocess.run(
            ["git", "-C", str(ROOT), "show", f"{BOARD_REV}:{BOARD_PATH_IN_REV}"],
            capture_output=True, text=True, check=True).stdout
    cx, cy = KICAD_ORIGIN
    parts = []
    for b in sexp_blocks(txt, "footprint"):
        name = re.search(r'\(footprint\s+"([^"]+)"', b).group(1)
        ref = re.search(r'\(property "Reference" "([^"]+)"', b)
        ref = ref.group(1) if ref else "?"
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", b)
        fx, fy, rot = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
        layer = re.search(r'\(layer "([^"]+)"\)', b).group(1)
        a = math.radians(-rot)
        ca, sa = math.cos(a), math.sin(a)
        pts = []
        for tag in ("fp_line", "fp_rect", "fp_poly", "fp_circle", "fp_arc"):
            for g in sexp_blocks(b, tag):
                if "CrtYd" not in g:
                    continue
                for m in re.finditer(r"\((?:start|end|mid|xy|center) ([-\d.]+) ([-\d.]+)\)", g):
                    pts.append((float(m.group(1)), float(m.group(2))))
        if not pts:
            for p in sexp_blocks(b, "pad"):
                m = re.search(r"\(at ([-\d.]+) ([-\d.]+)", p)
                z = re.search(r"\(size ([\d.]+) ([\d.]+)\)", p)
                if m and z:
                    px, py = float(m.group(1)), float(m.group(2))
                    w, h = float(z.group(1)) / 2, float(z.group(2)) / 2
                    pts += [(px - w, py - h), (px + w, py - h),
                            (px + w, py + h), (px - w, py + h)]
        if not pts:
            continue
        # KiCad (+y down) -> CAD (+y up)
        cad = [(fx + px * ca - py * sa - cx, -(fy + px * sa + py * ca - cy))
               for px, py in pts]
        parts.append({"ref": ref, "fp": name, "layer": layer,
                      "pos": (fx - cx, -(fy - cy)), "rot": rot,
                      "pts": cad, "h": part_height(name)})
    return parts


def convex_hull(pts):
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in pts))
    if len(pts) < 3:
        return pts

    def half(ps):
        st = []
        for p in ps:
            while len(st) >= 2 and ((st[-1][0] - st[-2][0]) * (p[1] - st[-2][1])
                                    - (st[-1][1] - st[-2][1]) * (p[0] - st[-2][0])) <= 0:
                st.pop()
            st.append(p)
        return st
    return half(pts)[:-1] + half(pts[::-1])[:-1]


def grow(hull, d):
    cx = sum(p[0] for p in hull) / len(hull)
    cy = sum(p[1] for p in hull) / len(hull)
    out = []
    for x, y in hull:
        dx, dy = x - cx, y - cy
        L = math.hypot(dx, dy) or 1.0
        out.append((x + dx / L * d, y + dy / L * d))
    return out


# ------------------------------------------------------------------ outline
class Outline:
    """Teardrop: circle of radius R truncated at y = tip_y by a flat of width
    tip_w, joined by the two tangent lines.  Offsetting outward by d keeps the
    construction: radius R+d, flat at tip_y+d, flanks shifted by d."""

    def __init__(self, R, tip_y, tip_w):
        self.R, self.tip_y, self.tip_w = R, tip_y, tip_w
        cr = (tip_w / 2, tip_y)
        self.ang = math.atan2(cr[1], cr[0]) - math.acos(R / math.hypot(*cr))
        tr = (R * math.cos(self.ang), R * math.sin(self.ang))
        vx, vy = cr[0] - tr[0], cr[1] - tr[1]          # tangency -> corner
        L = math.hypot(vx, vy)
        self.u = (vx / L, vy / L)
        n = (vy / L, -vx / L)
        if n[0] * cr[0] + n[1] * cr[1] < 0:
            n = (-n[0], -n[1])
        self.n = n                                     # outward normal, right flank
        self.kx = n[0] + self.u[0] * (1 - n[1]) / self.u[1]
        self.flank = L

    def corner(self, d=0.0):
        return (self.tip_w / 2 + self.kx * d, self.tip_y + d)

    def tangency(self, d=0.0):
        r = self.R + d
        return (r * math.cos(self.ang), r * math.sin(self.ang))

    def wire(self, d, z=0.0):
        r = self.R + d
        pr = self.tangency(d)
        pl = (-pr[0], pr[1])
        cr = self.corner(d)
        cl = (-cr[0], cr[1])
        V = lambda p: Vector(p[0], p[1], z)
        return Wire.assembleEdges([
            Edge.makeThreePointArc(V(pr), Vector(0, -r, z), V(pl)),
            Edge.makeLine(V(pl), V(cl)),
            Edge.makeLine(V(cl), V(cr)),
            Edge.makeLine(V(cr), V(pr))])

    def prism(self, d, z0, z1):
        return cq.Solid.extrudeLinear(self.wire(d, z0), [], Vector(0, 0, z1 - z0))

    def taper(self, d0, z0, d1, z1):
        return cq.Solid.makeLoft([self.wire(d0, z0), self.wire(d1, z1)], True)

    # arc-length parametrisation of the d = 0 outline, clockwise from the right
    # tangency, through the bottom, up the left flank, across the tip flat.
    def segs(self):
        # right tangency (angle +ang) clockwise the long way to the left one
        # (angle pi-ang, i.e. -pi-ang going clockwise): sweep = pi + 2*ang.
        return [self.R * (math.pi + 2 * self.ang), self.flank, self.tip_w, self.flank]

    def s_at_left_y(self, y):
        """Arc length of the point at height y on the LEFT side of the outline."""
        La, Lb, _, _ = self.segs()
        ty, cy = self.tangency()[1], self.corner()[1]
        if y >= ty:
            return La + Lb * (y - ty) / (cy - ty)
        lo, hi = La / 2, La                      # bottom of the arc .. left tangency
        for _ in range(60):
            mid = (lo + hi) / 2
            if self.R * math.sin(self.ang - mid / self.R) < y:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    def length(self):
        return sum(self.segs())

    def at(self, s, d=0.0):
        """(point, outward unit normal) at arc length s of the offset outline."""
        La, Lb, Lc, _ = self.segs()
        s %= self.length()
        if s <= La:
            a = self.ang - s / self.R
            nrm = (math.cos(a), math.sin(a))
            r = self.R + d
            return (r * nrm[0], r * nrm[1]), nrm
        s -= La
        pr, cr = self.tangency(), self.corner()
        pl, cl = (-pr[0], pr[1]), (-cr[0], cr[1])
        if s <= Lb:                                   # left flank, up
            f = s / Lb
            nrm = (-self.n[0], self.n[1])
            p = (pl[0] + (cl[0] - pl[0]) * f, pl[1] + (cl[1] - pl[1]) * f)
            return (p[0] + nrm[0] * d, p[1] + nrm[1] * d), nrm
        s -= Lb
        if s <= Lc:                                   # tip flat, left -> right
            f = s / Lc
            return (cl[0] + (cr[0] - cl[0]) * f, cl[1] + d), (0.0, 1.0)
        s -= Lc
        f = s / Lb                                    # right flank, down
        p = (cr[0] + (pr[0] - cr[0]) * f, cr[1] + (pr[1] - cr[1]) * f)
        return (p[0] + self.n[0] * d, p[1] + self.n[1] * d), self.n

    def s_at_angle(self, deg):
        a = math.radians(deg)
        while a > self.ang:
            a -= 2 * math.pi
        while a < self.ang - 2 * math.pi:
            a += 2 * math.pi
        return (self.ang - a) * self.R

    def s_at_point(self, p, n=4000):
        best, bs = 1e9, 0.0
        for i in range(n):
            s = self.length() * i / n
            q, _ = self.at(s)
            d = math.hypot(q[0] - p[0], q[1] - p[1])
            if d < best:
                best, bs = d, s
        return bs

    def poly(self, d, n=400):
        return [self.at(self.length() * i / n, d)[0] for i in range(n)]


def inside(poly, p):
    x, y = p
    r, j = False, len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            r = not r
        j = i
    return r


def dist_to_poly(poly, p):
    """Signed distance to a polygon: positive inside."""
    x, y = p
    best, n = 1e9, len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-9
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        best = min(best, math.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best if inside(poly, p) else -best


# ------------------------------------------------------------------ helpers
def band(ol, d0, d1, s0, s1, z0, z1, n=None):
    """Solid between offsets d0..d1 of the outline, over arc length s0..s1."""
    n = n or max(6, int(abs(s1 - s0) / 0.4))
    inner = [ol.at(s0 + (s1 - s0) * i / n, d0)[0] for i in range(n + 1)]
    outer = [ol.at(s0 + (s1 - s0) * i / n, d1)[0] for i in range(n + 1)]
    return (cq.Workplane("XY", origin=(0, 0, z0))
            .polyline(inner + outer[::-1]).close().extrude(z1 - z0).val())


def band_wire(ol, d0, d1, s0, s1, z, n=None):
    n = n or max(6, int(abs(s1 - s0) / 0.4))
    inner = [ol.at(s0 + (s1 - s0) * i / n, d0)[0] for i in range(n + 1)]
    outer = [ol.at(s0 + (s1 - s0) * i / n, d1)[0] for i in range(n + 1)]
    pts = inner + outer[::-1]
    return Wire.makePolygon([Vector(x, y, z) for x, y in pts] +
                            [Vector(pts[0][0], pts[0][1], z)])


def ring(ol, d0, d1, z0, z1):
    return ol.prism(d1, z0, z1).cut(ol.prism(d0, z0, z1))


def box_from(x0, x1, y0, y1, z0, z1):
    return (cq.Workplane("XY", origin=(0, 0, z0))
            .moveTo(x0, y0).lineTo(x1, y0).lineTo(x1, y1).lineTo(x0, y1)
            .close().extrude(z1 - z0).val())


def cut_all(shape, solids):
    """Pass the tools as separate arguments, never as one compound: OCC
    silently returns the shape unchanged when a compound's members overlap
    each other (a slot band and the snap hole drilled through it)."""
    return shape.cut(*solids) if solids else shape


def fuse_all(shape, solids):
    """Sequential fuse.  A single fuse against a compound leaves tool pieces
    that only touch each other (a lip riding on a finger) as loose solids."""
    for s in solids:
        shape = shape.fuse(s)
    return shape.clean() if solids else shape


def unify(shape):
    """Cutting along a plane that is coincident with an existing face leaves
    OCC holding several touching solids.  Re-fuse them; anything still loose
    afterwards is a real disconnect and the caller reports it."""
    sol = shape.Solids()
    if len(sol) < 2:
        return shape
    out = sol[0]
    for s in sol[1:]:
        out = out.fuse(s)
    return out.clean()


def hook(ol, s0, s1, lip, z_face, z_lip_end, z_tip):
    """Finger lip: flat catching face at z_face against the board, then a
    lead-in ramp that retracts flush with the finger by z_tip."""
    body = band(ol, -lip, EDGE_GAP + FINGER_T, s0, s1,
                min(z_face, z_lip_end), max(z_face, z_lip_end))
    ramp = cq.Solid.makeLoft(
        [band_wire(ol, -lip, EDGE_GAP + FINGER_T, s0, s1, z_lip_end),
         band_wire(ol, EDGE_GAP, EDGE_GAP + FINGER_T, s0, s1, z_tip)], True)
    return [body, ramp]


def obstacles(parts, layer):
    """[(ref, polygon, height)] keep-out footprints on one board face."""
    out = []
    for p in parts:
        if p["layer"] != layer:
            continue
        if p["ref"] == BAT_REF:
            n = 48
            out.append((p["ref"], [(BAT_CELL_R * math.cos(2 * math.pi * i / n),
                                    BAT_CELL_R * math.sin(2 * math.pi * i / n))
                                   for i in range(n)], p["h"]))
            hx, hy, hz = BAT_ARM
            out.append((p["ref"], [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)], hz))
            continue
        hull = grow(convex_hull(p["pts"]), KEEPOUT_XY)
        if len(hull) >= 3:
            out.append((p["ref"], hull, p["h"]))
    return out


def keepouts(parts, layer, zface, sign):
    """Keep-out prisms standing off the board face."""
    return [(cq.Workplane("XY", origin=(0, 0, zface))
             .polyline(poly).close().extrude(sign * (h + KEEPOUT_Z)).val())
            for _, poly, h in obstacles(parts, layer)]


# -------------------------------------------------------------------- build
def build(parts, ol, args, report):
    r_floor = -T_PCB - args.bat - R_FLOOR_GAP          # cup inner floor
    r_bot = r_floor - R_SHELL                          # cup outer face
    cell_pad_h = R_FLOOR_GAP + 0.10                    # 0.1 mm of preload

    leds = [p for p in parts if "LED_SK6805" in p["fp"]]
    mid_poly = ol.poly(-RING_BAND, 240)

    # ---- stations ---------------------------------------------------------
    stations = []
    for ang, owner in STATIONS:
        stations.append({"s": ol.s_at_angle(ang), "owner": owner,
                         "tag": f"{ang:.0f}", "hook_only": False})
    for sx in (-1, 1):
        f = (ol.corner()[1] - TIP_HOOK_Y) / (ol.corner()[1] - ol.tangency()[1])
        x = sx * (ol.corner()[0] + f * (ol.tangency()[0] - ol.corner()[0]))
        stations.append({"s": ol.s_at_point((x, TIP_HOOK_Y)), "owner": "front",
                         "tag": "tip" + ("L" if sx < 0 else "R"), "hook_only": True})
    for st in stations:
        st["s0"] = st["s"] - STATION_W / 2
        st["s1"] = st["s"] + STATION_W / 2
        st["p"], st["n"] = ol.at(st["s"])

    # measure every lip against the real keep-outs on the face it grabs
    hulls = {lay: [(r, poly) for r, poly, _ in obstacles(parts, lay)]
             for lay in ("F.Cu", "B.Cu")}
    for st in stations:
        lip = F_LIP if st["owner"] == "front" else R_LIP
        layer = "B.Cu" if st["owner"] == "front" else "F.Cu"
        worst, who = 99.0, ""
        for i in range(13):
            s = st["s0"] - 0.2 + (st["s1"] - st["s0"] + 0.4) * i / 12
            for k in range(5):
                q, _ = ol.at(s, -lip * k / 4)
                for ref, hull in hulls[layer]:
                    d = -dist_to_poly(hull, q)
                    if d < worst:
                        worst, who = d, ref
        st["clear"] = worst
        report.append(f"  station {st['tag']:>5s} {st['owner']:>5s}  lip {lip:.2f} mm"
                      f"  -> nearest {who:>5s} on {layer}  margin {worst:+.2f} mm"
                      + ("   *** TIGHT ***" if worst < 0.05 else ""))

    # ---- SW2 thumb scoop ---------------------------------------------------
    tipl = min((s for s in stations if s["tag"] == "tipL"),
               key=lambda s: s["s0"], default=None)
    s_lo = ol.s_at_left_y(NOTCH_Y0)
    s_hi = tipl["s0"] if tipl else ol.s_at_left_y(R_CLIP_Y)
    scoop = cq.Solid.makeLoft(
        [band_wire(ol, -R_LEDGE - 0.20, WALL + 0.6, s_lo + NOTCH_RAKE, s_hi,
                   NOTCH_Z, n=28),
         band_wire(ol, -R_LEDGE - 0.20, WALL + 0.6, s_lo, s_hi,
                   F_FLOOR_RING, n=28)], True)
    report.append(f"  SW2 thumb scoop: {s_hi - s_lo:.1f} mm along the rim, "
                  f"y {ol.at(s_lo)[0][1]:+.1f} to {ol.at(s_hi)[0][1]:+.1f}, "
                  f"z {NOTCH_Z:+.2f} to {F_FLOOR_RING:+.2f} "
                  f"({F_FLOOR_RING - NOTCH_Z:.2f} mm tall)")

    # ================================================================= FRONT
    front = ol.prism(WALL, F_FLOOR_RING, F_TOP - CHAMFER_H).fuse(
        ol.taper(WALL, F_TOP - CHAMFER_H, WALL - CHAMFER, F_TOP)).clean()
    front = front.cut(ol.prism(-RING_BAND, F_FLOOR_RING, F_FLOOR_MID))   # floor step
    front = front.fuse(ring(ol, EDGE_GAP, WALL, SEAM_Z, F_FLOOR_RING)).clean()
    front = front.fuse(ring(ol, -F_LEDGE, EDGE_GAP, 0.0, F_FLOOR_RING)).clean()

    bosses, pockets = [], []
    for p in leds:
        x, y = p["pos"]
        if inside(mid_poly, (x, y)):
            bosses.append(cq.Solid.makeCylinder(
                LED_BOSS_R, F_FLOOR_MID - F_FLOOR_RING, Vector(x, y, F_FLOOR_RING)))
        pockets.append(cq.Solid.makeCone(
            POCKET_R0, POCKET_R1, POCKET_TOP - F_FLOOR_RING,
            Vector(x, y, F_FLOOR_RING), Vector(0, 0, 1)))
    front = fuse_all(front, bosses)
    front = cut_all(front, pockets)

    add = []
    for st in stations:
        if st["owner"] != "front":
            continue
        add.append(band(ol, EDGE_GAP, EDGE_GAP + FINGER_T,
                        st["s0"], st["s1"], F_FINGER_Z, SEAM_Z))
        add += hook(ol, st["s0"], st["s1"], F_LIP, -T_PCB, F_LIP_END, F_FINGER_Z)
    front = fuse_all(front, add)

    cuts = []
    for st in stations:
        if st["owner"] != "rear":
            continue
        s0, s1 = st["s0"] - STATION_GAP, st["s1"] + STATION_GAP
        cuts.append(band(ol, -R_LIP - 0.15, WALL + 0.6, s0, s1,
                         SEAM_Z - 0.10, R_FINGER_Z))
    cuts.append(scoop)
    front = cut_all(front, cuts)

    front = front.cut(box_from(-40, 40, F_WALL_YMAX, 40, F_FINGER_Z - 1, F_FLOOR_RING))
    front = front.cut(box_from(-40, 40, F_CLIP_Y, 60, -10, 10))
    front = cut_all(front, keepouts(parts, "F.Cu", 0.0, +1))

    # ================================================================== REAR
    rear = ol.prism(WALL, r_bot + CHAMFER_H, SEAM_Z).fuse(
        ol.taper(WALL, r_bot + CHAMFER_H, WALL - CHAMFER, r_bot)).clean()
    rear = rear.cut(ol.prism(EDGE_GAP, r_floor, SEAM_Z + 1.0))          # cup interior
    # seat ledge: flat on top against the board, 45 deg underneath so it needs
    # no support when the cup prints outer-face-down
    zb = -T_PCB - 1.15 * (R_LEDGE + EDGE_GAP)      # ~54 deg, clear of the 45 limit
    ledge = ol.prism(EDGE_GAP, zb, -T_PCB).cut(ol.taper(-R_LEDGE, -T_PCB, EDGE_GAP, zb))
    rear = rear.fuse(ledge).clean()

    add = []
    for st in stations:
        if st["owner"] != "rear":
            continue
        add.append(band(ol, EDGE_GAP, EDGE_GAP + FINGER_T,
                        st["s0"], st["s1"], SEAM_Z, R_FINGER_Z))
        add += hook(ol, st["s0"], st["s1"], R_LIP, 0.0, R_LIP_END, R_FINGER_Z)
    rear = fuse_all(rear, add)

    cuts = []
    for st in stations:
        if st["owner"] != "front":
            continue
        s0, s1 = st["s0"] - STATION_GAP, st["s1"] + STATION_GAP
        cuts.append(band(ol, -F_LIP - 0.15, WALL + 0.6, s0, s1,
                         F_FINGER_Z - 0.15, SEAM_Z + 0.10))
    cuts.append(scoop)
    rear = cut_all(rear, cuts)

    rear = rear.cut(box_from(-40, 40, R_CLIP_Y, 60, r_bot - 5, 10))
    rear = cut_all(rear, keepouts(parts, "B.Cu", -T_PCB, -1))
    rear = rear.fuse(cq.Solid.makeCylinder(
        CELL_PAD_R, cell_pad_h, Vector(0, 0, r_floor))).clean()

    front, rear = unify(front), unify(rear)

    # ---- self-check --------------------------------------------------------
    board = ol.prism(0.0, -T_PCB, 0.0)
    for nm, shp, lay, zf, sgn in (("front", front, "F.Cu", 0.0, +1),
                                  ("rear", rear, "B.Cu", -T_PCB, -1)):
        probe = shp.cut(cq.Solid.makeCylinder(CELL_PAD_R + 0.1, 40,
                                              Vector(0, 0, r_floor - 1)))
        hit = sum(s.Volume() for k in keepouts(parts, lay, zf, sgn)
                  for s in [probe.intersect(k)])
        vb = shp.intersect(board).Volume()
        report.append(f"  {nm}: solids={len(shp.Solids())} shells={len(shp.Shells())} "
                      f"valid={shp.isValid()}  into parts {hit:.3f} mm3  "
                      f"into board {vb:.3f} mm3")
    clash = front.intersect(rear).Volume()
    report.append(f"  half-to-half interference: {clash:.3f} mm3")

    # The USB-C plug is the MOUNT (a loop soldered to a male plug), so it lives
    # in the connector permanently and its corridor has to stay clear.  Checked
    # generously: 14 x 8 mm about the receptacle opening, bigger than any
    # moulded cable end.
    zc = -T_PCB - 3.35 / 2
    plug = box_from(-7.0, 7.0, ol.tip_y - 0.2, 40, zc - 4.0, zc + 4.0)
    report.append(f"  mount-plug corridor (14 x 8 mm): front "
                  f"{front.intersect(plug).Volume():.3f}  rear "
                  f"{rear.intersect(plug).Volume():.3f} mm3 (want 0)")
    face = max((max(q[1] for q in p["pts"]) for p in parts if p["ref"] == "J1"),
               default=ol.tip_y)
    tipmax = max(v.Y for v in front.Vertices())
    report.append(f"  tip aperture: connector face y={face:+.2f}, diffuser flap "
                  f"ends y={tipmax:+.2f} ({face - tipmax:+.2f} mm clear); below "
                  f"z={F_FLOOR_RING:+.2f} the tip is fully open")

    # how much lip is actually hooked over each board face
    below = ol.prism(0.0, F_FINGER_Z, -T_PCB)
    above = ol.prism(0.0, 0.0, R_FINGER_Z)
    report.append(f"  clip engagement: front lips under the back face "
                  f"{front.intersect(below).Volume():.2f} mm3, rear lips over the "
                  f"front face {rear.intersect(above).Volume():.2f} mm3")

    return front, rear, dict(r_floor=r_floor, r_bot=r_bot, stations=stations)


# --------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", help="kicad_pcb to read (default: ordered rev via git)")
    ap.add_argument("--bat", type=float, default=5.30,
                    help="battery clip+cell height above the back face (mm)")
    ap.add_argument("--no-stl", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    parts = read_board(args.board)

    d = (ROOT / "design.yaml").read_text()
    R = float(re.search(r"round_radius_mm:\s*([\d.]+)", d).group(1))
    tip_y = float(re.search(r"tip_len_mm:\s*([\d.]+)", d).group(1))
    tip_w = float(re.search(r"tip_width_mm:\s*([\d.]+)", d).group(1))
    ol = Outline(R, tip_y, tip_w)

    rep = [f"board {BOARD_REV}: {len(parts)} footprints; outline R={R} "
           f"tip {tip_w}x{tip_y}; perimeter {ol.length():.1f} mm; "
           f"battery stack {args.bat:.2f} mm",
           f"clip stations (margins are to courtyards already grown by "
           f"{KEEPOUT_XY:.2f} mm, so add ~{KEEPOUT_XY:.2f} mm to reach the part body):"]
    front, rear, info = build(parts, ol, args, rep)

    for name, shp in (("earring-case-front", front), ("earring-case-rear", rear)):
        cq.exporters.export(cq.Workplane(obj=shp), str(OUT / f"{name}.step"))
        if not args.no_stl:
            cq.exporters.export(cq.Workplane(obj=shp), str(OUT / f"{name}.stl"),
                                tolerance=0.02, angularTolerance=0.15)
            # ...and again in print orientation: outer face flat on the bed at
            # z = 0, which is the only orientation that needs no supports.
            pr = shp.rotate(Vector(0, 0, 0), Vector(1, 0, 0), 180) \
                if name.endswith("front") else shp
            pr = pr.translate(Vector(0, 0, -pr.BoundingBox().zmin))
            cq.exporters.export(cq.Workplane(obj=pr), str(OUT / f"{name}-print.stl"),
                                tolerance=0.02, angularTolerance=0.15)
        bb = shp.BoundingBox()
        rep.append(f"{name}: {bb.xlen:.2f} x {bb.ylen:.2f} x {bb.zlen:.2f} mm  "
                   f"z[{bb.zmin:+.2f},{bb.zmax:+.2f}]  {shp.Volume()/1000:.2f} cm3  "
                   f"solids={len(shp.Solids())}")

    board = ol.prism(0.0, -T_PCB, 0.0)
    if not args.no_stl:
        cq.exporters.export(cq.Workplane(obj=board), str(OUT / "board-stub.stl"))
        # every part at its real footprint and height, for visual verification
        blocks = [s for lay, zf, sg in (("F.Cu", 0.0, +1), ("B.Cu", -T_PCB, -1))
                  for s in keepouts(parts, lay, zf, sg)]
        comps = cq.Compound.makeCompound(blocks)
        cq.exporters.export(cq.Workplane(obj=comps), str(OUT / "parts-stub.stl"))
        # capped half-sections, so the previews read as real cross-sections
        for tag, half in (("y", box_from(-40, 40, 0, 40, -20, 20)),
                          ("x", box_from(-40, 0, -40, 40, -20, 20))):
            for nm, shp in (("front", front), ("rear", rear),
                            ("board", board), ("parts", comps)):
                cq.exporters.export(cq.Workplane(obj=shp.cut(half)),
                                    str(OUT / f"sec{tag}-{nm}.stl"))
    asm = cq.Compound.makeCompound([front, rear, board])
    cq.exporters.export(cq.Workplane(obj=asm), str(OUT / "earring-case-assembly.step"))
    bb = asm.BoundingBox()
    rep.append(f"assembly: {bb.xlen:.2f} x {bb.ylen:.2f} x {bb.zlen:.2f} mm")
    rep.append(f"rear cup: inner floor z={info['r_floor']:+.2f}  outer face z={info['r_bot']:+.2f}")
    print("\n".join(rep))
    (OUT / "report.txt").write_text("\n".join(rep) + "\n")


if __name__ == "__main__":
    main()
