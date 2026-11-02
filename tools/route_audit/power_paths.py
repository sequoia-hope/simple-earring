# Power-path resistance: graph of copper items joined where KiCad's own shapes collide.
# A track costs its whole length (an upper bound when it is entered mid-way); pads cost 0; vias 1.1 mOhm.
import pcbnew, heapq, itertools, sys
b = pcbnew.LoadBoard('hw/earring/a/earring.kicad_pcb'); mm = pcbnew.ToMM
RHO = 1.72e-8; T = {'F.Cu': 35e-6, 'B.Cu': 35e-6, 'In1.Cu': 17.5e-6, 'In2.Cu': 17.5e-6}
LAY = [(l, b.GetLayerID(l)) for l in T]
def build(net):
    items = [t for t in b.GetTracks() if t.GetNetname() == net]
    items += [p for fp in b.GetFootprints() for p in fp.Pads() if p.GetNetname() == net]
    cost = []
    for it in items:
        if it.Type() == pcbnew.PCB_VIA_T: cost.append(0.0011)
        elif it.Type() == pcbnew.PCB_PAD_T: cost.append(0)
        else:
            l = b.GetLayerName(it.GetLayer())
            cost.append(RHO * mm(it.GetLength()) * 1e-3 / (mm(it.GetWidth()) * 1e-3 * T[l]))
    sh = [{l: it.GetEffectiveShape(lid) for l, lid in LAY if it.IsOnLayer(lid)} for it in items]
    adj = [[] for _ in items]
    for i, j in itertools.combinations(range(len(items)), 2):
        if any(l in sh[j] and sh[i][l].Collide(sh[j][l], 0) for l in sh[i]):
            adj[i].append(j); adj[j].append(i)
    return items, cost, adj
def path(net, A, B):
    items, cost, adj = build(net)
    idx = lambda r, n: next(i for i, it in enumerate(items) if it.Type() == pcbnew.PCB_PAD_T and it.GetParentFootprint().GetReference() == r and it.GetNumber() == n)
    s, d = idx(*A), idx(*B); dist = {s: 0}; prev = {}; pq = [(0, s)]
    while pq:
        c, u = heapq.heappop(pq)
        if u == d: break
        if c > dist[u]: continue
        for v in adj[u]:
            if c + cost[v] < dist.get(v, 1e9): dist[v] = c + cost[v]; prev[v] = u; heapq.heappush(pq, (c + cost[v], v))
    n = d; ln = 0; minw = 9; nv = 0; lay = {}
    while n in prev:
        it = items[n]
        if it.Type() == pcbnew.PCB_VIA_T: nv += 1
        elif it.Type() != pcbnew.PCB_PAD_T:
            w = mm(it.GetWidth()); l = b.GetLayerName(it.GetLayer()); ln += mm(it.GetLength()); minw = min(minw, w)
            lay[f"{l}@{w:.3g}"] = lay.get(f"{l}@{w:.3g}", 0) + mm(it.GetLength())
        n = prev[n]
    print(f"{net:6s} {A[0]}.{A[1]} -> {B[0]}.{B[1]}: {dist[d]*1000:4.0f} mOhm, {ln:5.1f} mm of track, narrowest {minw:.3g} mm, {nv} vias; "
          + ", ".join(f"{k} {v:.1f}" for k, v in sorted(lay.items(), key=lambda x: -x[1])))
for spec in sys.argv[1:]:
    net, a, c = spec.split(','); path(net, tuple(a.split(':')), tuple(c.split(':')))
