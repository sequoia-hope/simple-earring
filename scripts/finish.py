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
import shutil
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

# Canonical In3 east-pour polygon (6-layer only). route.py builds the zone
# from this; the south lobe reaches R15's 3V3 pad at (6.3,-13.86) while
# keeping 1.4mm from the J1 shell leg hole at (4.33,-14.88).
E3V3_POUR_PTS = [(4.2, -4.8), (11.2, -4.8), (11.2, -8.44), (8.9, -13.3),
                 (7.4, -14.3), (5.6, -14.3), (4.6, -13.3), (4.2, -9.5)]

# Radial bands where a through via lands in plane copper, per stackup.
# 6-layer: VLED lower bound 4.75 not 9.7 because In4 is a full VLED plane,
# so a via anywhere outside the clip back pad reaches it; 3V3 upper 8.7 is
# the In2 disc (9.55) less margin.
# 4-layer: no In4 and no In3, so VLED exists only as the In2 annulus
# (hole pulled in to r 9.35) and the 3V3 disc shrinks to 9.15 — see the
# zone block in route.py, which is the source of both radii.
_LAYER_PLANES = {
    6: ({"3V3": (0.0, 8.7), "GND": (0.0, 14.0), "VLED": (4.75, 14.0)},
        E3V3_POUR_PTS),
    4: ({"3V3": (0.0, 8.3), "GND": (0.0, 14.0), "VLED": (9.35, 14.0)},
        None),
}
_n_layers = load_design()["board"]["layers"]
PLANE_NETS, E3V3_POUR = _LAYER_PLANES[6 if _n_layers >= 6 else 4]


def _in_poly(q, poly):
    x, y = q
    inside = False
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (x1 - x0) * (y - y0) / (y1 - y0):
            inside = not inside
    return inside


def in_plane(net, q):
    """Would a via at q land inside net's plane copper (0.35mm margin)?"""
    band = PLANE_NETS.get(net)
    if band is None:
        return False
    lo, hi = band
    r = math.hypot(*q)
    if lo + 0.35 < r < hi - 0.35:
        return True
    if net == "3V3" and E3V3_POUR and _in_poly(q, E3V3_POUR):
        return all(seg_pt_dist(p0, p1, q) > 0.35 for p0, p1 in
                   zip(E3V3_POUR, E3V3_POUR[1:] + E3V3_POUR[:1]))
    return False
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


BEST = PCB.parent / "earring-best.kicad_pcb"
BEST_JSON = PCB.parent / "earring-best.json"


def keep_if_best(unc, errs, drc_data):
    """Snapshot this attempt if it beats the best one so far.

    build.py re-rolls route+finish on a new freerouting seed when the
    board doesn't converge, overwriting out/earring.kicad_pcb each time —
    so without this the LAST attempt survives, not the best one. When a
    stackup can't be closed automatically, the best partial plus a punch
    list is exactly what gets handed over for manual finishing.
    """
    score = (errs, unc)
    prev = None
    if BEST_JSON.exists():
        try:
            p = json.loads(BEST_JSON.read_text())
            prev = (p["errors"], p["unconnected"])
        except (ValueError, KeyError):
            prev = None
    if prev is not None and prev <= score:
        print(f"  (best so far stays {prev[1]} unconnected / "
              f"{prev[0]} errors)")
        return
    shutil.copyfile(PCB, BEST)
    stranded = sorted({net for net, _, _ in edges(drc_data)})
    BEST_JSON.write_text(json.dumps({
        "unconnected": unc, "errors": errs,
        "stranded_nets": stranded,
        "unconnected_edges": [
            {"net": net, "from": list(a), "to": list(b)}
            for net, a, b in edges(drc_data)],
    }, indent=2))
    print(f"  -> new best: {unc} unconnected / {errs} errors "
          f"saved to {BEST.name}"
          + (f" (stranded: {', '.join(stranded)})" if stranded else ""))


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
                # elongated pads: one capsule along the long axis (corner
                # error ~0.04mm). square-ish pads: capsule STRIPS across the
                # short axis — the old bounding circle inflated the QFN EP
                # from 1.7 to 2.4mm, sealing the 1mm routing cavity inside
                # the pin ring, and fattened every square LED pad by 41%
                ang = math.radians(p.GetOrientationDegrees())
                if w >= h:
                    ux, uy = math.cos(-ang), math.sin(-ang)
                    long_, short = w, h
                else:
                    ux, uy = math.sin(ang), math.cos(ang)
                    long_, short = h, w
                pxu, pyu = -uy, ux
                if long_ / max(short, 1e-6) >= 2.0:
                    strips = [(0.0, short / 2)]
                else:
                    ns = max(1, int(math.ceil(short / 0.5)))
                    sh = short / ns
                    strips = [(-short / 2 + (i + 0.5) * sh, sh / 2 * 1.25)
                              for i in range(ns)]
                layers = [ly for ly in (pcbnew.F_Cu, pcbnew.B_Cu)
                          if p.IsOnLayer(ly)]
                th = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
                for off, hw in strips:
                    hl = max(0.0, long_ / 2 - hw)
                    cx0, cy0 = x + off * pxu, y + off * pyu
                    a = (cx0 - hl * ux, cy0 - hl * uy)
                    b = (cx0 + hl * ux, cy0 + hl * uy)
                    self.items.append(
                        ("padc", layers, p.GetNetname(), a, b, hw, th))
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

    def clear_point(self, x, y, layer, net, need, is_via=False, pads=True):
        for it in self.near_items(x, y):
            kind = it[0]
            if kind == "padc" and not pads:
                continue
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
                # +0.02: segment sampling can step over a via ring by a
                # few um (seen live: 0.117 actual vs 0.127 rule)
                if inet != net and d < need + r + 0.02:
                    return False
            else:
                _, layers, inet, a, b, hw, th = it
                if inet == net:
                    continue
                relevant = is_via or th or (layer in layers)
                # +0.05: the capsule strips under-cover rectangular pad
                # CORNERS (rotated LGA/0402 pads grazed at 0.113-0.119
                # actual vs the 0.127 rule, seen live)
                if relevant and seg_pt_dist(a, b, (x, y)) < need + hw + 0.05:
                    return False
        return True

    def clear_seg(self, a, b, layer, net, need, pads=True):
        n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 0.15))
        return all(self.clear_point(a[0] + (b[0] - a[0]) * i / n,
                                    a[1] + (b[1] - a[1]) * i / n,
                                    layer, net, need, pads=pads)
                   for i in range(n + 1))


def to_rel(p):
    return (p.x / 1e6 - 100.0, p.y / 1e6 - 100.0)


def endpoint_layer(board, net, p):
    """Copper layer (F or B) of net's copper at DRC-edge endpoint p.
    Back-side pads (the IMU, relocated passives) need their stubs on B —
    the old finisher assumed F everywhere and reported 'no candidate' for
    every back-side edge. Vias/plane endpoints fall back to F."""
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    pos = pcbnew.VECTOR2I(int((p[0] + 100.0) * 1e6), int((p[1] + 100.0) * 1e6))
    on_f = on_b = False
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net and pad.HitTest(pos):
                on_f |= pad.IsOnLayer(F)
                on_b |= pad.IsOnLayer(B)
    if not (on_f or on_b):
        for t in board.GetTracks():
            if t.GetNetname() != net:
                continue
            if isinstance(t, pcbnew.PCB_VIA):
                if t.HitTest(pos):
                    return "any"   # via endpoint: any layer works
                continue
            for e in (t.GetStart(), t.GetEnd()):
                if abs(e.x - pos.x) < 50000 and abs(e.y - pos.y) < 50000:
                    if t.GetLayer() == F:
                        on_f = True
                    elif t.GetLayer() == B:
                        on_b = True
                    else:
                        return "any"   # inner-layer end (freerouting
                        # parks wires on plane layers): via-reachable
    if on_f:
        return F
    if on_b:
        return B
    return None
    # NB: F_Cu == 0 is FALSY — callers must compare against None
    # explicitly, never truth-test a returned layer (seen live: every
    # front-pad endpoint silently adopted the other side's layer)


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
    return True


def find_via_spot(obs, p, net, plane_net=None, stub_layer=None):
    """Search a clear via location near p (optionally inside net's plane
    copper). The stub from p is checked on stub_layer (default F)."""
    lay = stub_layer or pcbnew.F_Cu
    for r in (0.55, 0.8, 1.1, 1.5, 2.0):
        for k in range(16):
            th = 2 * math.pi * k / 16
            q = (p[0] + r * math.cos(th), p[1] + r * math.sin(th))
            if plane_net and not in_plane(plane_net, q):
                continue
            if not back_zone_ok(*q):
                continue
            if not obs.clear_point(*q, None, net, CLR + VIA_R, is_via=True):
                continue
            if not obs.clear_seg(p, q, lay, net, CLR + TRACK_W / 2):
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


def candidates(obs, net, a, b, la=None, lb=None):
    """Candidate link generators between endpoints a (on layer la) and b
    (on layer lb). la/lb default to F — B-side endpoints (back passives,
    the IMU) get their stubs and paths on B instead."""
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    la = la or F
    lb = lb or F
    need = CLR + TRACK_W / 2

    def seg_ok(p0, p1, lay):
        if lay == B and not (back_zone_ok(*p0) and back_zone_ok(*p1)):
            return False
        return obs.clear_seg(p0, p1, lay, net, need)

    # stub to nearby same-net copper on the endpoint's own layer
    # (vias reach all layers; track ends must match the stub layer)
    for p, lp in ((a, la), (b, lb)):
        for d, q, lay in samenet_targets(obs, net, p):
            if lay is not None and lay != lp:
                continue
            if seg_ok(p, q, lp):
                yield [("track", p, q, lp)]
    if net in PLANE_NETS:
        for p, lp in ((a, la), (b, lb)):
            q = find_via_spot(obs, p, net, plane_net=net, stub_layer=lp)
            if q:
                yield [("track", p, q, lp), ("via", q)]
    if la == lb:
        # same layer: direct, corner doglegs, and Z-paths with offsets
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
            if all(seg_ok(p0, p1, la) for p0, p1 in zip(pts, pts[1:])):
                yield [("track", p0, p1, la) for p0, p1 in zip(pts, pts[1:])]
    else:
        # mixed layers: single via joining the two endpoint layers
        for v in (find_via_spot(obs, a, net, stub_layer=la),
                  find_via_spot(obs, b, net, stub_layer=lb)):
            if v and seg_ok(a, v, la) and seg_ok(v, b, lb):
                yield [("track", a, v, la), ("via", v), ("track", v, b, lb)]
    # other-layer hop: via near each end, optional ring waypoint to skirt
    # the battery pad circle (only defined for same-layer endpoints; mixed
    # pairs are covered by the single-via case above)
    if la != lb:
        return
    hop = B if la == F else F
    va = find_via_spot(obs, a, net, stub_layer=la)
    vb = find_via_spot(obs, b, net, stub_layer=lb)
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
            segs = list(zip(pts, pts[1:]))
            if not all(seg_ok(p0, p1, hop) for p0, p1 in segs):
                continue
            if not (seg_ok(a, va, la) and seg_ok(vb, b, lb)):
                continue
            yield ([("track", a, va, la), ("via", va)]
                   + [("track", p0, p1, hop) for p0, p1 in segs]
                   + [("via", vb), ("track", vb, b, lb)])


def astar_route(obs, net, a, b, la=None, lb=None, r_board=14.4):
    """Coarse-grid A* over F.Cu/B.Cu with via transitions. Start/goal are
    handled as clear-cell rings around the endpoints (seeded on layer la,
    goal reached on layer lb); the first/last hops are straight unchecked
    segments (the DRC gate validates them)."""
    import heapq
    STEP = 0.1
    F, B = pcbnew.F_Cu, pcbnew.B_Cu
    la = la or F
    lb = lb or F
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
            node = (c[0], c[1], la)
            if node in parents or not ok(*c, la):
                continue
            # the implicit straight hop a->cell: short hops skip only PAD
            # clearance (own-pad shadow) — vias/tracks always checked (a
            # foreign via 0.6mm from an endpoint slipped through the old
            # fully-unchecked hop and cost a gate rejection every round)
            g = math.hypot(c[0] - a[0], c[1] - a[1])
            if g > 0.45 and not obs.clear_seg(a, c, la, net, need):
                continue
            if g <= 0.45 and not obs.clear_seg(a, c, la, net, need,
                                               pads=False):
                continue
            parents[node] = None
            push(g + h(*c), g, node, None)
    if not openq:
        # endpoint completely shadowed: seed the raw snapped endpoint
        c = snap(a)
        push(h(*c), 0.0, (c[0], c[1], la), None)
    seen = {}
    goal_node = None
    while openq:
        f, g, _t, node, par = heapq.heappop(openq)
        if node in seen:
            continue
        seen[node] = g
        parents[node] = par
        x, y, lay = node
        if lay == lb and h(x, y) < 1.2 and (
                (h(x, y) < 0.45 and obs.clear_seg((x, y), b, lb, net, need,
                                                  pads=False))
                or obs.clear_seg((x, y), b, lb, net, need)):
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
    prev = (a[0], a[1], la)  # implicit straight hop from a to the seed cell
    for nx, ny, nlay in path:
        px, py, play = prev
        if nlay != play:
            items.append(("via", (px, py)))
        elif (nx, ny) != (px, py):
            items.append(("track", (px, py), (nx, ny), nlay))
        prev = (nx, ny, nlay)
    items.append(("track", (prev[0], prev[1]), b, lb))
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


def drop_dangling_vias():
    """Unused speculative pre-vias leave dangling-via warnings and can pin
    isolated zone islands alive; delete them and refill."""
    r = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all",
         "-o", "/tmp/fin_all.json", str(PCB)], capture_output=True, text=True)
    if r.returncode not in (0, 5):
        return
    d = json.loads(Path("/tmp/fin_all.json").read_text())
    spots = []
    for v in d["violations"]:
        if v["type"] == "via_dangling":
            for i in v["items"]:
                spots.append((i["pos"]["x"] - 100.0, i["pos"]["y"] - 100.0))
    if not spots:
        return
    board = pcbnew.LoadBoard(str(PCB))
    n = 0
    for t in list(board.GetTracks()):
        if isinstance(t, pcbnew.PCB_VIA) and not t.IsLocked():
            # locked = deliberately pre-placed (plane access); a dangling
            # one just hasn't been picked up by the finisher yet
            x, y = to_rel(t.GetPosition())
            if any(abs(x - sx) < 0.05 and abs(y - sy) < 0.05 for sx, sy in spots):
                board.Delete(t)
                n += 1
    if n:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(PCB), board)
        print(f"dropped {n} dangling vias")


# Canonical VREG_LX path (matches the place.py cluster): pin 48 straight up
# x=-2.00 — the caps are centered on the LX pin column like the official
# minimal design, so the path threads their pad gap with 0.18mm to spare on
# both sides — then left into L1's LX pad. It rides inside the transplanted
# official LX pour (route.py) for the lower run; the pour is the primary
# copper, this spine guarantees connectivity if a fill hiccups.
LX_PATH = [(-2.00, 2.94), (-2.00, 6.82), (-2.70, 6.82)]


def synth_zone_edges(board, net="3V3"):
    """Split plane copper reports zone<->zone unconnected edges whose
    endpoints are zone anchor vertices A* can't act on. Works across ALL
    of net's zones/layers (In2 disc + In3 east pour + ...): cluster the
    filled fragments via the through-vias they share, then synthesize
    real edges from each via in a minority cluster to the nearest
    same-net via/pad of the rest — actual copper the normal candidate
    machinery can bridge. (Island removal is ALWAYS, so any surviving
    fragment contains at least one via.)"""
    ni = board.FindNet(net)
    if ni is None:
        return []
    code = ni.GetNetCode()
    frags = []
    for zz in board.Zones():
        if zz.GetNetCode() != code or zz.GetIsRuleArea():
            continue
        for lay in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu,
                    pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.B_Cu):
            if not zz.IsOnLayer(lay):
                continue
            polys = zz.GetFilledPolysList(lay)
            for i in range(polys.OutlineCount()):
                sp = pcbnew.SHAPE_POLY_SET()
                sp.AddOutline(polys.Outline(i))
                frags.append(sp)
    if len(frags) < 2:
        return []
    vias = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)
            and t.GetNetCode() == code]
    parent = list(range(len(frags)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    via_frags = []      # (via rel pos, [fragment indices containing it])
    for v in vias:
        pos = v.GetPosition()
        touched = [i for i, sp in enumerate(frags) if sp.Contains(pos)]
        for i, j in zip(touched, touched[1:]):
            parent[find(i)] = find(j)
        via_frags.append((to_rel(pos), touched))
    clusters = {}
    for i in range(len(frags)):
        clusters.setdefault(find(i), []).append(i)
    if len(clusters) < 2:
        return []
    main = max(clusters, key=lambda c: sum(
        abs(frags[i].Outline(0).Area()) for i in clusters[c]))
    anchors_main = [p for p, touched in via_frags
                    if any(find(i) == main for i in touched)]
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == code:
                anchors_main.append(to_rel(pad.GetPosition()))
    minority = [p for p, touched in via_frags
                if touched and all(find(i) != main for i in touched)]
    out = []
    for a in minority:
        srt = sorted(anchors_main,
                     key=lambda m: (m[0] - a[0]) ** 2 + (m[1] - a[1]) ** 2)
        for b in srt[:3]:   # gate rejects useless bridges; try a few
            out.append((net, a, b))
    if out:
        print(f"zone-split {net}: {len(frags)} fragments in "
              f"{len(clusters)} clusters, synthesized {len(out)} edges")
    return out


def drop_stub_vias():
    """Delete unlocked 3V3/VLED plane-fanout vias that touch no same-net
    track end or pad: they connect nothing but a zone fragment, and a lone
    via pins an isolated In2 disc island alive — which reads as a
    permanent zone-to-zone unconnected edge."""
    board = pcbnew.LoadBoard(str(PCB))
    vias = [t for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA)
            and not t.IsLocked() and t.GetNetname() in ("3V3", "VLED")]
    if not vias:
        return
    ends = {}
    for t in board.GetTracks():
        if isinstance(t, pcbnew.PCB_VIA):
            continue
        for p in (t.GetStart(), t.GetEnd()):
            ends.setdefault(t.GetNetname(), []).append((p.x, p.y))
    pads = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            pads.setdefault(p.GetNetname(), []).append(p)
    n = 0
    for v in vias:
        pos = v.GetPosition()
        net = v.GetNetname()
        r = v.GetWidth(pcbnew.F_Cu) // 2 + pcbnew.FromMM(0.05)
        if any((ex - pos.x) ** 2 + (ey - pos.y) ** 2 <= r * r
               for ex, ey in ends.get(net, ())):
            continue
        if any(p.HitTest(pos) for p in pads.get(net, ())):
            continue
        board.Delete(v)
        n += 1
    if n:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(PCB), board)
        print(f"dropped {n} stub plane vias")


def widen_lx():
    """RP2350 ds §6.3.8 asks for minimal parasitics on the VREG_LX node.
    Replace freerouting's wiring with the canonical centered path, as wide
    as clearance allows (DRC-verified, restores the original on failure —
    e.g. if the cluster placement has moved and LX_PATH is stale)."""
    errs0, unc0, _ = drc_counts(PCB)
    board = pcbnew.LoadBoard(str(PCB))
    net = board.FindNet("VREG_LX")
    if net is None:
        return
    rt = Router(board, load_design())
    orig = []
    for t in list(board.GetTracks()):
        if t.GetNetCode() == net.GetNetCode() and \
                not isinstance(t, pcbnew.PCB_VIA):
            # copy coords by value: the VECTOR2Is returned by GetStart/End
            # dangle once the track is Delete()d
            s, e = t.GetStart(), t.GetEnd()
            orig.append((s.x, s.y, e.x, e.y, t.GetWidth(), t.GetLayer()))
            board.Delete(t)
    for w in (0.20,):
        created = [rt.track(vec(*a), vec(*b), "VREG_LX", width=w,
                            locked=False)
                   for a, b in zip(LX_PATH, LX_PATH[1:])]
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(str(PCB), board)
        errs, unc, _ = drc_counts(PCB)
        if errs <= errs0 and unc <= unc0:
            print(f"VREG_LX re-laid centered at {w}mm")
            return
        for t in created:
            board.Delete(t)
    for sx, sy, ex, ey, w0, lay in orig:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pcbnew.VECTOR2I(sx, sy))
        t.SetEnd(pcbnew.VECTOR2I(ex, ey))
        t.SetWidth(w0)
        t.SetLayer(lay)
        t.SetNet(net)
        board.Add(t)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    print("VREG_LX kept as freerouting laid it (canonical path failed DRC)")


def main():
    design = load_design()
    drop_dangling_vias()
    for rnd in range(6):
        errs0, unc0, d0 = drc_counts(PCB)
        todo = edges(d0)
        if not todo:
            break
        print(f"round {rnd}: {len(todo)} edges, {errs0} errors")
        board = pcbnew.LoadBoard(str(PCB))
        rt = Router(board, design)
        obs = Obstacles(board)
        # zone<->zone edges (degenerate same-point, or cross-zone with
        # both endpoints on zone anchors, e.g. In3 pour <-> split In2
        # disc) -> real copper pairs
        todo2 = []
        synthed = set()
        for net, a, b in todo:
            degen = abs(a[0] - b[0]) < 0.01 and abs(a[1] - b[1]) < 0.01
            zonly = (endpoint_layer(board, net, a) is None
                     and endpoint_layer(board, net, b) is None)
            if degen or zonly:
                if net not in synthed:
                    synthed.add(net)
                    todo2.extend(synth_zone_edges(board, net))
            else:
                todo2.append((net, a, b))
        todo = todo2
        progress = False
        for net, a, b in todo:
            fixed = False
            # a via/zone endpoint (None) adopts the other side's layer so
            # same-layer candidates and A* stay available. Compare against
            # None explicitly: F_Cu == 0 is falsy!
            la = endpoint_layer(board, net, a)
            lb = endpoint_layer(board, net, b)
            if la == "any":
                la = None
            if lb == "any":
                lb = None
            if la is None:
                la = lb if lb is not None else pcbnew.F_Cu
            if lb is None:
                lb = la

            def anchors(p, lp):
                # 4.6mm radius: an endpoint's fragment can extend well past
                # 2mm (e.g. LED2's VCC reaches the plane only via LED1's
                # fanout, one LED pitch + pad offset away). Dedupe: padc
                # strips of one pad share near-identical centers. Each
                # anchor carries the layer of its pad copper.
                F, B = pcbnew.F_Cu, pcbnew.B_Cu
                cands = []
                for it in obs.items:
                    if it[0] == "padc" and it[2] == net:
                        c = ((it[3][0] + it[4][0]) / 2,
                             (it[3][1] + it[4][1]) / 2)
                        d = math.hypot(c[0] - p[0], c[1] - p[1])
                        if d < 4.6:
                            lay = F if F in it[1] or it[6] else B
                            cands.append((d, c, lay))
                    elif it[0] == "via" and it[2] == net:
                        # same-net vias anchor on any layer — the only
                        # reachable copper when freerouting dead-ends a
                        # net on an inner plane layer
                        c = (it[3], it[4])
                        d = math.hypot(c[0] - p[0], c[1] - p[1])
                        if d < 4.6:
                            cands.append((d, c, lp))
                cands.sort()
                out = [(p, lp)]
                for d, c, lay in cands:
                    if all(math.hypot(c[0] - o[0][0], c[1] - o[0][1]) > 0.6
                           for o in out):
                        out.append((c, lay))
                return out[:4]

            def all_cands():
                yield from candidates(obs, net, a, b, la, lb)
                for aa, laa in anchors(a, la):
                    for bb, lbb in anchors(b, lb):
                        c = astar_route(obs, net, aa, bb, laa, lbb)
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
                print(f"  {net}: gate rejected "
                      f"(errs {errs0}->{errs}, unc {unc0}->{unc})")
                for c in created:
                    board.Delete(c)
            if not fixed:
                print(f"  {net}: no candidate ({a} -> {b})")
        pcbnew.SaveBoard(str(PCB), board)
        if not progress:
            break
    # final: drop dead plane stubs, widen the LX node, refill zones, report
    drop_stub_vias()
    widen_lx()
    board = pcbnew.LoadBoard(str(PCB))
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    errs, unc, unc_nets = drc_counts(PCB)
    print(f"finish: {unc} unconnected, {errs} errors remain")
    keep_if_best(unc, errs, unc_nets)
    sys.exit(0 if unc == 0 and errs == 0 else 1)


if __name__ == "__main__":
    main()
