# Track joints that rely on copper overlap rather than a shared endpoint: report the joint's neck width.
import pcbnew, math, collections, sys
b = pcbnew.LoadBoard(sys.argv[1] if len(sys.argv) > 1 else 'hw/earring/a/earring.kicad_pcb'); mm = pcbnew.ToMM
tr = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_TRACE_T]
vias = [t for t in b.GetTracks() if t.Type() == pcbnew.PCB_VIA_T]
P = lambda v: (mm(v.x), mm(v.y))
def segdist(p, a, c):
    ax, ay = a; cx, cy = c; L2 = (cx-ax)**2 + (cy-ay)**2
    f = 0 if L2 == 0 else max(0, min(1, ((p[0]-ax)*(cx-ax) + (p[1]-ay)*(cy-ay)) / L2))
    return math.hypot(p[0]-(ax+f*(cx-ax)), p[1]-(ay+f*(cy-ay))), f
by = collections.defaultdict(list)
for t in tr: by[(t.GetNetname(), t.GetLayer())].append(t)
pads = collections.defaultdict(list)
for fp in b.GetFootprints():
    for pd in fp.Pads(): pads[pd.GetNetname()].append(pd)
out = []
for (net, lay), ts in by.items():
    for t in ts:
        r1 = mm(t.GetWidth()) / 2
        for end in (t.GetStart(), t.GetEnd()):
            p = P(end)
            # ends inside a via or pad of the net are joined by that land
            if any(v.GetNetname() == net and math.hypot(*(a-b_ for a, b_ in zip(p, P(v.GetPosition())))) <= mm(v.GetWidth(pcbnew.F_Cu))/2 for v in vias): continue
            if any(pd.IsOnLayer(lay) and pd.HitTest(end, 0) for pd in pads[net]): continue
            best = None; joined = False
            for u in ts:
                if u is t: continue
                d, f = segdist(p, P(u.GetStart()), P(u.GetEnd()))
                if d <= 0.005: joined = True; break
                r2 = mm(u.GetWidth()) / 2
                if d < r1 + r2:
                    if d <= r2: neck = 2*r1 if d + r1 <= r2 else 2*math.sqrt(max(0, r1*r1 - (d - r2)**2)) if d > r2 else 2*r1
                    else: neck = 2*math.sqrt(max(0, r1*r1 - (d - r2)**2))
                    neck = min(neck, 2*r1, 2*r2)
                    if best is None or neck > best[0]: best = (neck, d)
            if joined or best is None: continue
            out.append((best[0], net, b.GetLayerName(lay), p, best[1], mm(t.GetWidth())))
out.sort()
print(f"{len(out)} overlap-only joints")
for neck, net, l, p, d, w in out:
    print(f"neck {neck:.3f} mm  {net:14s} {l:7s} at ({p[0]:.3f},{p[1]:.3f})  centre offset {d:.3f}  width {w:.3g}")
