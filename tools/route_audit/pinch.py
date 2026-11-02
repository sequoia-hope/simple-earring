# Where a net's copper pinches under the minimum width on one layer: the location KiCad's
# connection_width check measures but reports only at the zone's origin.
# Caveat (gate 7 review, 2026-11-02): pairs on one ring within 3x the minimum along the outline are
# skipped as corners, so a small track joint can be missed; check those by erosion.
# usage: python3 tools/route_audit/pinch.py BOARD NET LAYER   (e.g. ... GND F_Cu)
import sys, pcbnew, numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import Polygon
from shapely.ops import unary_union
b=pcbnew.LoadBoard(sys.argv[1]); net=sys.argv[2]; L=getattr(pcbnew,sys.argv[3]); MIN=0.09
def sp(ps):
    out=[]
    for i in range(ps.OutlineCount()):
        o=ps.Outline(i); pts=[(o.CPoint(k).x/1e6,o.CPoint(k).y/1e6) for k in range(o.PointCount())]
        holes=[[(ps.Hole(i,h).CPoint(k).x/1e6,ps.Hole(i,h).CPoint(k).y/1e6) for k in range(ps.Hole(i,h).PointCount())] for h in range(ps.HoleCount(i))]
        if len(pts)>2: out.append(Polygon(pts,holes))
    return out
g=[]
for z in b.Zones():
    if z.GetNetname()==net and not z.GetIsRuleArea() and z.IsOnLayer(L): g+=sp(z.GetFilledPolysList(L))
for fp in b.GetFootprints():
    for p in fp.Pads():
        if p.GetNetname()==net and p.IsOnLayer(L):
            ps=pcbnew.SHAPE_POLY_SET(); p.TransformShapeToPolygon(ps,L,0,1000,pcbnew.ERROR_INSIDE); g+=sp(ps)
for t in b.GetTracks():
    if t.GetNetname()==net and t.IsOnLayer(L):
        ps=pcbnew.SHAPE_POLY_SET(); t.TransformShapeToPolygon(ps,L,0,1000,pcbnew.ERROR_INSIDE); g+=sp(ps)
cu=unary_union(g)
polys=getattr(cu,'geoms',[cu])
pts=[];ring=[];arc=[]
rid=0
for P in polys:
    for R in [P.exterior]+list(P.interiors):
        R=R.segmentize(0.005); c=np.array(R.coords)[:-1]
        s=np.concatenate([[0],np.cumsum(np.hypot(*np.diff(np.vstack([c,c[:1]]),axis=0).T))])
        per=s[-1]; s=s[:-1]
        pts.append(c); ring+= [rid]*len(c); arc.append(np.c_[s,np.full(len(s),per)]); rid+=1
pts=np.vstack(pts); ring=np.array(ring); arc=np.vstack(arc)
T=cKDTree(pts); res=[]
for i,j in T.query_pairs(MIN):
    d=np.hypot(*(pts[i]-pts[j]))
    if ring[i]==ring[j]:
        a=abs(arc[i,0]-arc[j,0]); a=min(a,arc[i,1]-a)
        if a < 3*MIN: continue   # same corner
    # the chord must lie inside copper (a neck), not across a gap
    from shapely.geometry import LineString
    mid=LineString([pts[i],pts[j]]).interpolate(0.5,normalized=True)
    if not cu.contains(mid): continue
    res.append((d,tuple(np.round(pts[i],3)),tuple(np.round(pts[j],3)),ring[i]==ring[j]))
res.sort()
seen=[]
for d,a,c,same in res:
    if any(np.hypot(a[0]-s[0],a[1]-s[1])<0.3 for s in seen): continue
    seen.append(a); print(f'{d:.4f}  {a} {c} {"same ring" if same else "two rings"}')
    if len(seen)>8: break
