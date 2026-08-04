#!/usr/bin/env python3
"""Verify locked (pre-placed) copper geometry against a board snapshot.

Usage: python3 scripts/check_locked_copper.py [board.kicad_pcb]

Edit the chain lists below to describe the geometry under test, then run
against a PRE-ROUTE board save (route.py saves one before freerouting).
A locked-wire clearance violation makes freerouting burn its entire 900s
budget, so EVERY locked segment/via change must pass this before a build.
The embedded chains are the USB diff pair as shipped - kept as a worked
example and regression reference.
"""
_ORIG_DOC = """
Models: axis-aligned pads as rects, rotated pads as bounding discs, NPTH
holes, pre-placed vias, other locked tracks; checks segment crossings,
via-vs-everything, and cross-net pair separation. R6/R7 SWAP AWARE: pass
the snapshot taken AFTER place.py moved them, or use --swap to relocate
R6/R7 pads in the model before checking."""
import pcbnew, math, sys

SNAP = sys.argv[1] if len(sys.argv) > 1 else "out/earring.kicad_pcb"
TH, CL = 0.075, 0.127
F, B = "F", "B"

# geometry v2

DM_C = [
    (F, (-0.75, -13.55), (0.25, -13.55)),
    (B, (-0.75, -13.55), (-0.75, -12.60)),
    (B, (-0.75, -12.60), (-0.85, -12.35)),
    (B, (-0.85, -12.35), (-0.85, -12.04)),
    (B, (0.85, -12.04), (-0.85, -12.04)),
    (B, (-0.85, -12.35), (-4.75, -12.35)),
    (B, (-4.75, -12.35), (-4.75, -8.30)),
    (B, (-4.75, -8.30), (-5.10, -7.95)),
    (B, (-5.10, -7.95), (-5.10, 6.55)),
    (B, (-5.10, 6.55), (2.45, 6.55)),
    (B, (2.45, 6.55), (2.45, 7.05)),
    (F, (2.45, 7.05), (2.10, 6.55)),
    (F, (2.10, 6.55), (2.10, 5.35)),
    (F, (2.10, 5.35), (1.80, 5.05)),
    (F, (1.80, 5.05), (1.59, 4.75)),
]
DP_C = [
    (B, (-0.25, -14.60), (-0.25, -15.00)),
    (B, (0.75, -14.60), (0.75, -15.00)),
    (F, (-0.25, -15.00), (0.75, -15.00)),
    (B, (0.75, -15.00), (0.75, -13.00)),
    (B, (0.75, -13.00), (1.62, -12.55)),
    (B, (1.62, -12.55), (1.62, -11.10)),
    (B, (1.62, -11.10), (1.10, -10.96)),
    (B, (1.10, -10.96), (-0.85, -10.96)),
    (B, (-0.85, -10.96), (-4.45, -10.96)),
    (B, (-4.45, -10.96), (-4.34, -10.80)),
    (B, (-4.34, -10.80), (-4.34, -9.40)),
    (F, (-4.34, -9.40), (-5.40, -8.75)),
    (B, (-5.40, -8.75), (-5.40, 6.85)),
    (B, (-5.40, 6.85), (1.05, 6.85)),
    (B, (1.05, 6.85), (1.05, 7.05)),
    (F, (1.05, 7.05), (1.45, 6.35)),
    (F, (1.45, 6.35), (1.59, 5.95)),
]
DM = [
    (F, (-0.80, 2.94), (-0.80, 3.42)),
    (F, (-0.80, 3.42), (-0.60, 3.92)),
    (F, (-0.60, 3.92), (0.30, 4.10)),
    (F, (0.30, 4.10), (2.20, 4.20)),
    (F, (2.20, 4.20), (2.61, 4.55)),
]
DP = [
    (F, (-0.40, 2.94), (-0.40, 3.65)),
    (F, (-0.40, 3.65), (3.30, 3.65)),
    (F, (3.30, 3.65), (3.30, 5.90)),
    (F, (3.30, 5.90), (2.61, 5.90)),
]
VBUS = [
    (F, (-2.35, -13.45), (-0.50, -12.40)),
    (F, (-0.50, -12.40), (0.92, -11.50)),
    (F, (0.92, -11.50), (1.60, -12.20)),
    (F, (1.60, -12.20), (2.35, -13.45)),
]
FB = [
    (F, (-1.20, 3.30), (-1.20, 3.66)),
    (F, (-1.20, 3.66), (-1.02, 3.66)),
    (F, (-1.02, 3.66), (-1.02, 4.44)),
]
VIAS = [("USB_DP_C", (-4.34, -9.40)), ("USB_DP_C", (-5.40, -8.75)),
        ("USB_DM_C", (2.45, 7.05)), ("USB_DP_C", (1.05, 7.05)),
        ("VBUS", (-2.35, -13.45)), ("VBUS", (0.92, -11.50)),
        ("VBUS", (2.35, -13.45))]
CHAINS = [("USB_DM_C", DM_C), ("USB_DP_C", DP_C),
          ("USB_DM", DM), ("USB_DP", DP), ("VBUS", VBUS),
          ("VDD_CORE", FB)]


b = pcbnew.LoadBoard(SNAP)
def rel(p): return (p.x/1e6-100, p.y/1e6-100)
obs = {F: [], B: []}
for fp in b.GetFootprints():
    for p in fp.Pads():
        x, y = rel(p.GetPosition())
        # apply the R6/R7 swap to the model
        if fp.GetReference() == "R6": y += 1.15
        elif fp.GetReference() == "R7": y -= 1.15
        sz = p.GetSize(pcbnew.F_Cu); w, h = sz.x/1e6, sz.y/1e6
        rot = p.GetOrientationDegrees() % 180
        name = fp.GetReference()+"."+p.GetNumber(); net = p.GetNetname()
        attr = p.GetAttribute()
        layers = [F, B] if attr in (pcbnew.PAD_ATTRIB_NPTH, pcbnew.PAD_ATTRIB_PTH) else \
                 [L for L, ly in ((F, pcbnew.F_Cu), (B, pcbnew.B_Cu)) if p.IsOnLayer(ly)]
        if attr == pcbnew.PAD_ATTRIB_NPTH:
            item = ('disc', x, y, p.GetDrillSize().x/2e6 + 0.15, name, net)
        elif abs(rot) < 1 or abs(rot-90) < 1:
            hx, hy = (w/2, h/2) if abs(rot) < 1 else (h/2, w/2)
            item = ('rect', x, y, hx, hy, name, net)
        else:
            item = ('disc', x, y, math.hypot(w, h)/2, name, net)
        for L in layers: obs[L].append(item)
for t in b.GetTracks():
    if isinstance(t, pcbnew.PCB_VIA):
        x, y = rel(t.GetPosition())
        if t.GetNetname() in ("USB_DM_C", "USB_DP_C") and y > 4:
            continue  # superseded end vias
        for L in (F, B): obs[L].append(('disc', x, y, 0.2, "via", t.GetNetname()))
    else:
        if t.GetNetname() in ("USB_DM_C", "USB_DP_C", "USB_DM", "USB_DP", "VDD_CORE", "VBUS"):
            continue  # replacing all locked USB tracks
        a, e = rel(t.GetStart()), rel(t.GetEnd())
        L = F if t.GetLayer() == pcbnew.F_Cu else B
        obs[L].append(('seg', a, e, TH, "trk", t.GetNetname()))

def pdist(px, py, a, e):
    ax, ay = a; ex, ey = e; dx, dy = ex-ax, ey-ay
    L2 = dx*dx+dy*dy
    t = 0 if L2 == 0 else max(0, min(1, ((px-ax)*dx+(py-ay)*dy)/L2))
    return math.hypot(ax+t*dx-px, ay+t*dy-py)
def rect_seg(cx, cy, hx, hy, a, e, n=80):
    best = 9e9
    for i in range(n+1):
        px = a[0]+(e[0]-a[0])*i/n; py = a[1]+(e[1]-a[1])*i/n
        dx = max(abs(px-cx)-hx, 0); dy = max(abs(py-cy)-hy, 0)
        d = math.hypot(dx, dy)
        if abs(px-cx) < hx and abs(py-cy) < hy: d = -1
        best = min(best, d)
    return best
def segseg(a1, e1, a2, e2):
    def ccw(A, Bp, C): return (C[1]-A[1])*(Bp[0]-A[0]) > (Bp[1]-A[1])*(C[0]-A[0])
    if ccw(a1, a2, e2) != ccw(e1, a2, e2) and ccw(a1, e1, a2) != ccw(a1, e1, e2):
        return -1
    return min(pdist(*a1, a2, e2), pdist(*e1, a2, e2),
               pdist(*a2, a1, e1), pdist(*e2, a1, e1))

bad = []
for net, chain in CHAINS:
    for L, a, e in chain:
        for o in obs[L]:
            if o[0] == 'rect':
                _, cx, cy, hx, hy, name, onet = o
                if onet == net: continue
                d = rect_seg(cx, cy, hx, hy, a, e) - CL - TH
            elif o[0] == 'disc':
                _, x, y, r, name, onet = o
                if onet == net: continue
                d = pdist(x, y, a, e) - r - CL - TH
            else:
                _, oa, oe, r, name, onet = o
                if onet == net: continue
                d = segseg(a, e, oa, oe) - r - CL - TH
            if d < 0.005: bad.append((net, a, e, name, round(d, 3)))
for vnet, (vx, vy) in VIAS:
    for L in (F, B):
        for o in obs[L]:
            if o[0] == 'rect':
                _, cx, cy, hx, hy, name, onet = o
                if onet == vnet: continue
                dx = max(abs(vx-cx)-hx, 0); dy = max(abs(vy-cy)-hy, 0)
                d = math.hypot(dx, dy) - 0.2 - CL
            elif o[0] == 'disc':
                _, x, y, r, name, onet = o
                if onet == vnet: continue
                d = math.hypot(x-vx, y-vy) - r - 0.2 - CL
            else:
                _, oa, oe, r, name, onet = o
                if onet == vnet: continue
                d = pdist(vx, vy, oa, oe) - r - 0.2 - CL
            if d < 0.005: bad.append(("via@"+vnet, (vx, vy), None, name, round(d, 3)))
# cross-net among the four locked chains + vias vs other chains
for i, (n1, c1) in enumerate(CHAINS):
    for n2, c2 in CHAINS[i+1:]:
        if n2 == n1: continue
        for L1, a1, e1 in c1:
            for L2, a2, e2 in c2:
                if L1 != L2: continue
                d = segseg(a1, e1, a2, e2) - (2*TH + CL)
                if d < 0.005: bad.append((f"{n1}~{n2}", a1, e1, f"{a2}->{e2}", round(d, 3)))
for vnet, (vx, vy) in VIAS:
    for n2, c2 in CHAINS:
        if n2 == vnet: continue
        for L, a, e in c2:
            d = pdist(vx, vy, a, e) - 0.2 - CL - TH
            if d < 0.005: bad.append((f"via@{vnet}~{n2}", (vx, vy), None, f"{a}->{e}", round(d, 3)))
for i, (n1, v1) in enumerate(VIAS):
    for n2, v2 in VIAS[i+1:]:
        d = math.hypot(v1[0]-v2[0], v1[1]-v2[1])
        if n1 != n2 and d < 0.4 + CL + 0.005: bad.append(("via~via", v1, v2, "", round(d, 3)))
        if d < 0.527: bad.append(("hole~hole", v1, v2, "", round(d, 3)))
if bad:
    print("VIOLATIONS:")
    for x in bad: print("  ", x)
else:
    print("ALL CLEAR")
