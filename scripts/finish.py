#!/usr/bin/env python3
"""Finish stage: complete the few connections freerouting plateaus on.

Rounds until convergence:
  1. DRC -> unconnected edges (net, endpoint A, endpoint B).
  2. For each edge, generate obstacle-aware candidates:
     - plane nets: stub + via into the plane at a searched clear spot
     - direct / dogleg segments on F.Cu or B.Cu (clearance-sampled)
     - F -> B -> F via hop
  3. Add candidate, run real DRC; keep only if errors don't increase and
     the edge actually resolves (or total unconnected drops).

The obstacle index is a flat list of copper items; clearance checks are
sampled, then the authoritative DRC gates every accepted candidate.
"""
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import load_design  # noqa: E402
from route import Router, vec, mm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"

PLANE_NETS = {"3V3": (0.0, 8.7), "GND": (0.0, 14.0), "VLED": (9.7, 14.0)}
BATT_PAD_R = 4.6
CLR = 0.13          # sampled clearance target (rule is 0.127)
TRACK_W = 0.15
VIA_R = 0.2


def drc_counts(pcb_path):
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        rep = f.name
    r = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-error",
         "-o", rep, str(pcb_path)], capture_output=True, text=True)
    if r.returncode not in (0, 5):
        raise RuntimeError(r.stderr)
    d = json.loads(Path(rep).read_text())
    Path(rep).unlink()
    return len(d["violations"]), len(d["unconnected_items"]), d


def edges(drc_data):
    out = []
    for u in drc_data["unconnected_items"]:
        pts, net = [], None
        for i in u["items"]:
            pts.append((round(i["pos"]["x"] - 100.0, 3),
                        round(i["pos"]["y"] - 100.0, 3)))
            if "[" in i["description"]:
                net = i["description"].split("[")[1].split("]")[0]
        if len(pts) == 2 and net:
            out.append((net, pts[0], pts[1]))
    return out


class Obstacles:
    """Flat copper index for sampled clearance checks."""

    def __init__(self, board):
        self.items = []  # (kind, layer_set, net, geometry...)
        for t in board.GetTracks():
            net = t.GetNetname()
            if isinstance(t, pcbnew.PCB_VIA):
                x, y = to_rel(t.GetPosition())
                self.items.append(("via", None, net, x, y,
                                   t.GetWidth(pcbnew.F_Cu) / 2e6))
            else:
                a = to_rel(t.GetStart())
                b = to_rel(t.GetEnd())
                self.items.append(("seg", t.GetLayer(), net, a, b,
                                   t.GetWidth() / 2e6))
        for fp in board.GetFootprints():
            for p in fp.Pads():
                x, y = to_rel(p.GetPosition())
                sz = p.GetSize(pcbnew.F_Cu)
                w, h = sz.x / 1e6, sz.y / 1e6
                # elongated pads: capsule along the long axis (corner error
                # ~0.04mm). square-ish pads: bounding circle — the inscribed
                # capsule misses corners by up to 0.3*short (0.7mm on the EP)
                ang = math.radians(p.GetOrientationDegrees())
                if max(w, h) / max(min(w, h), 1e-6) < 2.0:
                    hl, hw = 0.0, math.hypot(w, h) / 2
                    ux, uy = 1.0, 0.0
                elif w >= h:
                    hl, hw = (w - h) / 2, h / 2
                    ux, uy = math.cos(-ang), math.sin(-ang)
                else:
                    hl, hw = (h - w) / 2, w / 2
                    ux, uy = math.sin(ang), math.cos(ang)
                a = (x - hl * ux, y - hl * uy)
                b = (x + hl * ux, y + hl * uy)
                layers = [ly for ly in (pcbnew.F_Cu, pcbnew.B_Cu)
                          if p.IsOnLayer(ly)]
                th = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                self.items.append(("padc", layers, p.GetNetname(), a, b, hw, th))
        # 1mm spatial bins over item bboxes inflated by 0.7mm
        self.bins = {}
        for idx, it in enumerate(self.items):
            if it[0] == "via":
                xs, ys = [it[3]], [it[4]]
            else:
                xs = [it[3][0], it[4][0]]
                ys = [it[3][1], it[4][1]]
            for bx in range(int(math.floor(min(xs) - 0.7)),
                            int(math.floor(max(xs) + 0.7)) + 1):
                for by in range(int(math.floor(min(ys) - 0.7)),
                                int(math.floor(max(ys) + 0.7)) + 1):
                    self.bins.setdefault((bx, by), []).append(idx)

    def near_items(self, x, y):
        return (self.items[i]
                for i in self.bins.get((int(math.floor(x)), int(math.floor(y))), ()))

    def clear_point(self, x, y, layer, net, need, is_via=False):
        for it in self.near_items(x, y):
            kind = it[0]
            if kind == "seg":
                _, lay, inet, a, b, hw = it
                if inet == net:
                    continue
                if not is_via and lay != layer:
                    continue
                if seg_pt_dist(a, b, (x, y)) < need + hw:
                    return False
            elif kind == "via":
                _, _, inet, ix, iy, r = it
                d = math.hypot(ix - x, iy - y)
                if is_via and d < 0.55:      # hole-to-hole
                    return False
                if inet != net and d < need + r:
                    return False
            else:
                _, layers, inet, a, b, hw, th = it
                if inet == net:
                    continue
                relevant = is_via or th or (layer in layers)
                if relevant and seg_pt_dist(a, b, (x, y)) < need + hw:
                    return False
        return True

    def clear_seg(self, a, b, layer, net, need):
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.25))
        return all(self.clear_point(a[0] + (b[0] - a[0]) * i / n,
                                    a[1] + (b[1] - a[1]) * i / n,
                                    layer, net, need)
                   for i in range(n + 1))


def to_rel(p):
    return (p.x / 1e6 - 100.0, p.y / 1e6 - 100.0)


def seg_pt_dist(a, b, p):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def back_zone_ok(x, y):
    if math.hypot(x, y) < BATT_PAD_R:
        return False
    if abs(y) < 3.4 and 10.1 < abs(x) < 14.4:
        return False
    if -9.7 < x < -3.5 and -14.3 < y < -8.5:  # SW1 at 240 deg
        return False
    return True


def find_via_spot(obs, p, net, plane=None):
    """Search a clear via location near p (optionally inside a plane band)."""
    for r in (0.55, 0.8, 1.1, 1.5, 2.0):
        for k in range(16):
            th = 2 * math.pi * k / 16
            q = (p[0] + r * math.cos(th), p[1] + r * math.sin(th))
            if plane:
                lo, hi = plane
                if not (lo + 0.35 < math.hypot(*q) < hi - 0.35):
                    continue
            if not back_zone_ok(*q):
                continue
            if not obs.clear_point(*q, None, net, CLR + VIA_R, is_via=True):
                continue
            # the stub must also be clear on F
            if not obs.clear_seg(p, q, pcbnew.F_Cu, net, CLR + TRACK_W / 2):
                continue
            return q
    return None


def samenet_targets(obs, net, p, radius=3.0):
    """Nearby same-net copper attach points, nearest first."""
    out = []
    for it in obs.items:
        if it[0] == "via":
            _, _, inet, ix, iy, r = it
            if inet != net:
                continue
            d = math.hypot(ix - p[0], iy - p[1])
            if 0.05 < d < radius:
                out.append((d, (ix, iy), None))
        elif it[0] == "seg":
            _, lay, inet, a, b, hw = it
            if inet != net:
                continue
            for q in (a, b):
                d = math.hypot(q[0] - p[0], q[1] - p[1])
                if 0.05 < d < radius:
                    out.append((d, q, lay))
    out.sort(key=lambda t: t[0])
    return out[:5]


def candidates(obs, net, a, b):
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    need = CLR + TRACK_W / 2
    # stub to nearby same-net copper (vias reach all layers; track ends
    # must be on F to join with a front stub)
    for p in (a, b):
        for d, q, lay in samenet_targets(obs, net, p):
            if lay is not None and lay != F:
                continue
            if obs.clear_seg(p, q, F, net, need):
                yield [("track", p, q, F)]
    plane = PLANE_NETS.get(net)
    if plane:
        for p in (a, b):
            q = find_via_spot(obs, p, net, plane)
            if q:
                yield [("track", p, q, F), ("via", q)]
    # front: direct, corner doglegs, and Z-paths with escape offsets
    paths = [[a, b], [a, (a[0], b[1]), b], [a, (b[0], a[1]), b],
             [a, ((a[0] + b[0]) / 2, a[1]), b],
             [a, ((a[0] + b[0]) / 2, b[1]), b]]
    for off in (0.7, 1.0, 1.4):
        for s in (1, -1):
            ex = a[0] + s * off
            paths.append([a, (ex, a[1]), (ex, b[1]), b])
            ey = a[1] + s * off
            paths.append([a, (a[0], ey), (b[0], ey), b])
            ex = b[0] + s * off
            paths.append([a, (ex, a[1]), (ex, b[1]), b])
    for pts in paths:
        if all(obs.clear_seg(p0, p1, F, net, need)
               for p0, p1 in zip(pts, pts[1:])):
            yield [("track", p0, p1, F) for p0, p1 in zip(pts, pts[1:])]
    # back hop: via near each end, optional ring waypoint to skirt the
    # battery pad circle
    va = find_via_spot(obs, a, net)
    vb = find_via_spot(obs, b, net)
    if va and vb:
        mid_cands = [None]
        tha = math.atan2(va[1], va[0])
        thb = math.atan2(vb[1], vb[0])
        dth = (thb - tha + math.pi) % (2 * math.pi) - math.pi
        for r in (6.3, 7.6):
            mid_cands.append((r * math.cos(tha + dth / 2),
                              r * math.sin(tha + dth / 2)))
        mid_cands += [(va[0], vb[1]), (vb[0], va[1])]
        for m in mid_cands:
            pts = [va, vb] if m is None else [va, m, vb]
            if not all(back_zone_ok(*p) for p in pts):
                continue
            segs = list(zip(pts, pts[1:]))
            if not all(obs.clear_seg(p0, p1, B, net, need) for p0, p1 in segs):
                continue
            if not (obs.clear_seg(a, va, F, net, need)
                    and obs.clear_seg(vb, b, F, net, need)):
                continue
            yield ([("track", a, va, F), ("via", va)]
                   + [("track", p0, p1, B) for p0, p1 in segs]
                   + [("via", vb), ("track", vb, b, F)])


def astar_route(obs, net, a, b, r_board=14.4):
    """Coarse-grid A* over F.Cu/B.Cu with via transitions. Start/goal are
    handled as clear-cell rings around the endpoints; the first/last hops
    are straight unchecked segments (the DRC gate validates them)."""
    import heapq
    STEP = 0.1
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    need = CLR + TRACK_W / 2

    def ok(x, y, layer):
        if math.hypot(x, y) > r_board - 0.45:
            return False
        if layer == B and not back_zone_ok(x, y):
            return False
        return obs.clear_point(x, y, layer, net, need)

    def via_ok(x, y):
        return (back_zone_ok(x, y)
                and obs.clear_point(x, y, None, net, CLR + VIA_R, is_via=True))

    def snap(p):
        return (b[0] + round((p[0] - b[0]) / STEP) * STEP,
                b[1] + round((p[1] - b[1]) / STEP) * STEP)

    h = lambda x, y: math.hypot(b[0] - x, b[1] - y)
    openq = []
    parents = {}
    tick = [0]
    def push(f, g, node, par):
        tick[0] += 1
        heapq.heappush(openq, (f, g, tick[0], node, par))
    # seed: clear cells around a (straight hop a->cell is implicit)
    for r in [i * STEP for i in range(0, 21)]:
        nseed = max(1, int(2 * math.pi * r / STEP)) if r else 1
        for k in range(nseed):
            th = 2 * math.pi * k / nseed
            c = snap((a[0] + r * math.cos(th), a[1] + r * math.sin(th)))
            node = (c[0], c[1], F)
            if node in parents or not ok(*c, F):
                continue
            # the implicit straight hop a->cell: unchecked only when very
            # short (own-pad shadow); longer hops must be clear
            g = math.hypot(c[0] - a[0], c[1] - a[1])
            if g > 0.45 and not obs.clear_seg(a, c, F, net, need):
                continue
            parents[node] = None
            push(g + h(*c), g, node, None)
    if not openq:
        # endpoint completely shadowed: seed the raw snapped endpoint
        c = snap(a)
        push(h(*c), 0.0, (c[0], c[1], F), None)
    seen = {}
    goal_node = None
    while openq:
        f, g, _t, node, par = heapq.heappop(openq)
        if node in seen:
            continue
        seen[node] = g
        parents[node] = par
        x, y, lay = node
        if lay == F and h(x, y) < 1.2 and (
                h(x, y) < 0.45 or obs.clear_seg((x, y), b, F, net, need)):
            goal_node = node
            break
        if len(seen) > 250000:
            return None
        for dx, dy in ((STEP, 0), (-STEP, 0), (0, STEP), (0, -STEP),
                       (STEP, STEP), (STEP, -STEP), (-STEP, STEP),
                       (-STEP, -STEP)):
            nx, ny = round(x + dx, 4), round(y + dy, 4)
            nn = (nx, ny, lay)
            if nn in seen or not ok(nx, ny, lay):
                continue
            ng = g + math.hypot(dx, dy)
            push(ng + h(nx, ny), ng, nn, node)
        other = B if lay == F else F
        if via_ok(x, y) and (x, y, other) not in seen:
            ng = g + 1.2
            push(ng + h(x, y), ng, (x, y, other), node)
    if goal_node is None:
        return None
    path = [goal_node]
    while parents[path[-1]] is not None:
        path.append(parents[path[-1]])
    path.reverse()
    items = []
    prev = (a[0], a[1], F)   # implicit straight hop from a to the seed cell
    for nx, ny, nlay in path:
        px, py, play = prev
        if nlay != play:
            items.append(("via", (px, py)))
        elif (nx, ny) != (px, py):
            items.append(("track", (px, py), (nx, ny), nlay))
        prev = (nx, ny, nlay)
    items.append(("track", (prev[0], prev[1]), b, F))
    # merge collinear runs
    merged = []
    for it in items:
        if (merged and it[0] == "track" and merged[-1][0] == "track"
                and merged[-1][3] == it[3]):
            p0, p1 = merged[-1][1], merged[-1][2]
            q1 = it[2]
            v1 = (p1[0] - p0[0], p1[1] - p0[1])
            v2 = (q1[0] - p1[0], q1[1] - p1[1])
            if abs(v1[0] * v2[1] - v1[1] * v2[0]) < 1e-9:
                merged[-1] = ("track", p0, q1, it[3])
                continue
        merged.append(it)
    return merged


def main():
    design = load_design()
    for rnd in range(6):
        errs0, unc0, d0 = drc_counts(PCB)
        todo = edges(d0)
        if not todo:
            break
        print(f"round {rnd}: {len(todo)} edges, {errs0} errors")
        board = pcbnew.LoadBoard(str(PCB))
        rt = Router(board, design)
        obs = Obstacles(board)
        progress = False
        for net, a, b in todo:
            fixed = False
            def anchors(p):
                out = [p]
                for it in obs.items:
                    if it[0] == "padc" and it[2] == net:
                        c = ((it[3][0] + it[4][0]) / 2,
                             (it[3][1] + it[4][1]) / 2)
                        if math.hypot(c[0] - p[0], c[1] - p[1]) < 2.0:
                            out.append(c)
                return out[:3]

            def all_cands():
                yield from candidates(obs, net, a, b)
                for aa in anchors(a):
                    for bb in anchors(b):
                        c = astar_route(obs, net, aa, bb)
                        if c:
                            yield c
                            return
            for cand in all_cands():
                created = []
                for it in cand:
                    if it[0] == "track":
                        created.append(rt.track(vec(*it[1]), vec(*it[2]), net,
                                                layer=it[3], width=TRACK_W,
                                                locked=False))
                    else:
                        created.append(rt.via(it[1], net, locked=False))
                pcbnew.ZONE_FILLER(board).Fill(board.Zones())
                pcbnew.SaveBoard(str(PCB), board)
                errs, unc, d = drc_counts(PCB)
                if errs <= errs0 and unc < unc0:
                    unc0 = unc
                    desc = "+".join(i[0] for i in cand)
                    print(f"  {net}: {desc} OK")
                    fixed = progress = True
                    break
                for c in created:
                    board.Delete(c)
            if not fixed:
                print(f"  {net}: no candidate ({a} -> {b})")
        pcbnew.SaveBoard(str(PCB), board)
        if not progress:
            break
    # final: refill zones, report
    board = pcbnew.LoadBoard(str(PCB))
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    errs, unc, _ = drc_counts(PCB)
    print(f"finish: {unc} unconnected, {errs} errors remain")
    sys.exit(0 if unc == 0 and errs == 0 else 1)


if __name__ == "__main__":
    main()
