#!/usr/bin/env python3
"""Teardrop outline geometry (all coords center-relative mm, +y down;
the tip points UP, i.e. toward -y).

Shape: circle of radius R centered at origin, truncated tip at y=-tip_y
with half-width tip_w/2, joined to the circle by the two tangent lines
through the tip corners.

Provides:
  params(design)                -> (R, tip_y, tip_w)
  outline_points(design, n)     -> closed polygon, CCW-on-screen
  edge_geometry(design)         -> dict with arc + line segments for Edge.Cuts
  led_path(design, margin, end_clear) -> path object with .length,
        .point(s) -> (x, y), .tangent(s) -> unit vector
  offset_polygon(design, d, n)  -> outline shrunk inward by d
  half_width_at(design, y)      -> outline half width at height y
"""
import math


def params(design):
    b = design["board"]
    R = b.get("round_radius_mm", b.get("diameter_mm", 30.5) / 2)
    tip_y = b.get("tip_len_mm", 20.5)
    tip_w = b.get("tip_width_mm", 9.4)
    return R, tip_y, tip_w


def _tangency(R, corner):
    """Polar angle (rad) of the tangency point of the line from `corner`
    to the circle radius R, choosing the point on the corner's side."""
    cx, cy = corner
    d = math.hypot(cx, cy)
    base = math.atan2(cy, cx)
    delta = math.acos(R / d)
    # two candidates; pick the one whose x has the corner's sign and larger |x|
    cands = [base + delta, base - delta]
    pts = [(R * math.cos(a), R * math.sin(a)) for a in cands]
    pick = max(range(2), key=lambda i: pts[i][0] * math.copysign(1, cx))
    return cands[pick]


def geometry(design):
    R, tip_y, tip_w = params(design)
    cr = (tip_w / 2, -tip_y)   # right tip corner
    cl = (-tip_w / 2, -tip_y)
    ar = _tangency(R, cr)      # right tangency polar angle (rad)
    al = _tangency(R, cl)
    pr = (R * math.cos(ar), R * math.sin(ar))
    pl = (R * math.cos(al), R * math.sin(al))
    return {"R": R, "tip_y": tip_y, "tip_w": tip_w,
            "corner_r": cr, "corner_l": cl,
            "tang_r": pr, "tang_l": pl,
            "ang_r": ar, "ang_l": al}


def outline_points(design, n_arc=140):
    g = geometry(design)
    pts = []
    # arc from right tangency, the long way through the bottom (+y), to left
    a0 = g["ang_r"]
    a1 = g["ang_l"]
    # go in increasing angle direction (through +90deg bottom)
    while a1 < a0:
        a1 += 2 * math.pi
    for i in range(n_arc + 1):
        a = a0 + (a1 - a0) * i / n_arc
        pts.append((g["R"] * math.cos(a), g["R"] * math.sin(a)))
    pts.append(g["corner_l"])
    pts.append(g["corner_r"])
    return pts


def half_width_at(design, y):
    g = geometry(design)
    R = g["R"]
    if y >= g["tang_r"][1]:          # round region (works for |y|<R)
        return math.sqrt(max(0.0, R * R - y * y))
    if y <= -g["tip_y"]:
        return g["tip_w"] / 2
    # straight region: interpolate corner..tangency
    (tx, ty), (cx, cy) = g["tang_r"], g["corner_r"]
    f = (y - cy) / (ty - cy)
    return cx + f * (tx - cx)


class _Path:
    """Piecewise path: list of ('line', p0, p1) / ('arc', c, r, a0, a1)."""

    def __init__(self, segs):
        self.segs = segs
        self.lens = []
        for s in segs:
            if s[0] == "line":
                self.lens.append(math.dist(s[1], s[2]))
            else:
                _, c, r, a0, a1 = s
                self.lens.append(abs(a1 - a0) * r)
        self.length = sum(self.lens)

    def point(self, s):
        for seg, L in zip(self.segs, self.lens):
            if s > L:
                s -= L
                continue
            f = s / L if L else 0
            if seg[0] == "line":
                (x0, y0), (x1, y1) = seg[1], seg[2]
                return (x0 + (x1 - x0) * f, y0 + (y1 - y0) * f)
            _, c, r, a0, a1 = seg
            a = a0 + (a1 - a0) * f
            return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
        return self.point(self.length - 1e-9)

    def tangent(self, s):
        for seg, L in zip(self.segs, self.lens):
            if s > L:
                s -= L
                continue
            f = s / L if L else 0
            if seg[0] == "line":
                (x0, y0), (x1, y1) = seg[1], seg[2]
                d = math.dist((x0, y0), (x1, y1))
                return ((x1 - x0) / d, (y1 - y0) / d)
            _, c, r, a0, a1 = seg
            a = a0 + (a1 - a0) * f
            sgn = 1 if a1 > a0 else -1
            return (-math.sin(a) * sgn, math.cos(a) * sgn)
        return self.tangent(self.length - 1e-9)

    def normal_in(self, s, design):
        """Unit normal pointing into the board."""
        x, y = self.point(s)
        tx, ty = self.tangent(s)
        # candidates: rotate tangent +-90; pick the one pointing toward origin-ish
        n1 = (-ty, tx)
        n2 = (ty, -tx)
        return n1 if (n1[0] * -x + n1[1] * -y) > 0 else n2


def led_path(design, margin, end_clear_y):
    """Inward-offset perimeter path for LEDs: starts on the LEFT straight at
    y = end_clear_y (near the tip), runs down, around the bottom, up the
    RIGHT straight to y = end_clear_y. Chain order = index order."""
    g = geometry(design)
    R = g["R"]
    Ri = R - margin

    def offset_line(corner, tang):
        # shift the corner->tangency line inward by `margin`
        dx, dy = tang[0] - corner[0], tang[1] - corner[1]
        L = math.hypot(dx, dy)
        # inward normal: toward origin
        nx, ny = -dy / L, dx / L
        if nx * (-corner[0]) + ny * (-corner[1]) < 0:
            nx, ny = -nx, -ny
        return ((corner[0] + nx * margin, corner[1] + ny * margin),
                (tang[0] + nx * margin, tang[1] + ny * margin))

    lc, lt = offset_line(g["corner_l"], g["tang_l"])
    rc, rt = offset_line(g["corner_r"], g["tang_r"])

    def clip_to_y(p0, p1, y):
        f = (y - p0[1]) / (p1[1] - p0[1])
        return (p0[0] + (p1[0] - p0[0]) * f, y)

    l_start = clip_to_y(lc, lt, end_clear_y)
    r_end = clip_to_y(rc, rt, end_clear_y)
    # inner arc endpoints: tangency angles are the same for the offset arc
    a_l = g["ang_l"]
    a_r = g["ang_r"]
    while a_l < a_r:
        a_l += 2 * math.pi
    # path: left line (down to left tangency), arc left->right going through
    # bottom means DECREASING angle from a_l to a_r? Arc CCW-on-screen from
    # right to left was a_r->a_l increasing; we travel the opposite way:
    lt_i = (Ri * math.cos(a_l), Ri * math.sin(a_l))
    rt_i = (Ri * math.cos(a_r), Ri * math.sin(a_r))
    segs = [("line", l_start, lt_i),
            ("arc", (0.0, 0.0), Ri, a_l, a_r),
            ("line", rt_i, r_end)]
    return _Path(segs)


def offset_polygon(design, d, n_arc=100):
    """Inward offset via per-vertex normal shift (outline is convex)."""
    pts = outline_points(design, n_arc)
    n = len(pts)
    out = []
    for i in range(n):
        p_prev = pts[(i - 1) % n]
        p = pts[i]
        p_next = pts[(i + 1) % n]
        # edge normals (inward = toward origin)
        def enorm(a, b):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy) or 1e-9
            nx, ny = -dy / L, dx / L
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if nx * -mid[0] + ny * -mid[1] < 0:
                nx, ny = -nx, -ny
            return nx, ny
        n1 = enorm(p_prev, p)
        n2 = enorm(p, p_next)
        nx, ny = n1[0] + n2[0], n1[1] + n2[1]
        L = math.hypot(nx, ny) or 1e-9
        # miter length correction
        cosh = max(0.4, (1 + (n1[0] * n2[0] + n1[1] * n2[1])) / 2) ** 0.5
        out.append((p[0] + nx / L * d / cosh, p[1] + ny / L * d / cosh))
    return out


if __name__ == "__main__":
    import yaml
    from pathlib import Path as P
    design = yaml.safe_load((P(__file__).parent.parent / "design.yaml").read_text())
    g = geometry(design)
    print("tangency R:", g["tang_r"], "L:", g["tang_l"])
    p = led_path(design, 2.0, -13.2)
    print("led path length:", round(p.length, 1))
    for s in (0, p.length / 2, p.length):
        print("  ", [round(v, 2) for v in p.point(s)], [round(v, 2) for v in p.tangent(s)])
