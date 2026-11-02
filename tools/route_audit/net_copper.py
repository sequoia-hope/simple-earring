# Per-net copper summary of the routed board: tracks, widths, layers, vias, zone fills.
import pcbnew, collections, sys
b = pcbnew.LoadBoard('hw/earring/a/earring.kicad_pcb')
mm = pcbnew.ToMM
L = lambda l: b.GetLayerName(l)
tr = collections.defaultdict(list); vias = collections.Counter()
for t in b.GetTracks():
    n = t.GetNetname()
    if t.Type() == pcbnew.PCB_VIA_T: vias[n] += 1
    else: tr[n].append((L(t.GetLayer()), mm(t.GetWidth()), mm(t.GetLength()), t.IsLocked()))
zones = collections.defaultdict(list)
for z in b.Zones():
    if z.GetIsRuleArea(): continue
    for l in z.GetLayerSet().Seq():
        fp = z.GetFilledPolysList(l)
        zones[z.GetNetname()].append((L(l), fp.OutlineCount(), round(fp.Area()/1e12, 1)))
nets = sorted(set(tr) | set(zones) | set(vias))
print("net | tracks | len mm | min w | w<0.2 len | layers | vias | zones(layer,pieces,mm2)")
for n in nets:
    ts = tr.get(n, [])
    if not ts and not zones.get(n): continue
    mw = min((t[1] for t in ts), default=0)
    print(n, '|', len(ts), '|', round(sum(t[2] for t in ts),1), '|', mw, '|',
          round(sum(t[2] for t in ts if t[1] < 0.2),1), '|',
          dict(collections.Counter(t[0] for t in ts)), '|', vias[n], '|', zones.get(n, ''))
print('tracks on In1:', [(n,t) for n,ts in tr.items() for t in ts if t[0]=='In1.Cu'][:20])
