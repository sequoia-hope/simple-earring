#!/usr/bin/env python3
"""Routing pipeline.

1. Wipe existing tracks/vias/zones (idempotent).
2. Scripted, locked routing for the regular structures:
   - LED daisy-chain as constant-radius arcs on F.Cu
   - via drops: every LED VCC pad -> In2 VLED annulus, GND pad -> In1 plane
   - bypass cap via drops
   - VBATT feed: B.Cu tracks from battery clip feet to front-side vias
   - GND stitching vias
3. Zones: In1=GND plane, In2=VLED annulus + 3V3 disc, F/B GND pours.
4. Freerouting (Specctra DSN -> SES) for the remaining point-to-point nets.
5. Zone fill + save; report unconnected count.

Run with --no-freeroute to skip step 4 (faster placement iteration).
"""
import math
import subprocess
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
JAR = ROOT / "tools" / "freerouting.jar"
CX, CY = 100.0, 100.0


def mm(v):
    return pcbnew.FromMM(v)


def to_mm(iu):
    return pcbnew.ToMM(iu)


def vec(x, y):
    return pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))


def rel(p):
    """VECTOR2I -> center-relative mm tuple"""
    return (to_mm(p.x) - CX, to_mm(p.y) - CY)


def radius(p):
    x, y = rel(p)
    return math.hypot(x, y)


class Router:
    def __init__(self, board, design):
        self.board = board
        self.design = design
        self.j = design["jlcpcb"]
        self.nets = {}

    def net(self, name):
        if name not in self.nets:
            ni = self.board.FindNet(name)
            assert ni is not None, f"net {name} not found"
            self.nets[name] = ni
        return self.nets[name]

    def track(self, a, b, netname, layer=pcbnew.F_Cu, width=None, locked=True):
        t = pcbnew.PCB_TRACK(self.board)
        t.SetStart(a if isinstance(a, pcbnew.VECTOR2I) else vec(*a))
        t.SetEnd(b if isinstance(b, pcbnew.VECTOR2I) else vec(*b))
        t.SetLayer(layer)
        t.SetWidth(mm(width or self.j["default_track_mm"]))
        t.SetNet(self.net(netname))
        t.SetLocked(locked)
        self.board.Add(t)
        return t

    def arc(self, a, b, netname, layer=pcbnew.F_Cu, width=None, locked=True,
            nseg=4):
        """Chorded arc between points a,b (VECTOR2I), center near board
        center. Emitted as nseg straight chords: freerouting chokes on locked
        PCB_ARC obstacles, and at ring radius the sagitta is <0.1mm."""
        ax, ay = rel(a)
        bx, by = rel(b)
        # center of arc: point on perpendicular bisector closest to board center
        mxp, myp = (ax + bx) / 2, (ay + by) / 2
        dx, dy = bx - ax, by - ay
        px, py = -dy, dx
        norm = math.hypot(px, py)
        px, py = px / norm, py / norm
        s = -(mxp * px + myp * py)
        cx0, cy0 = mxp + s * px, myp + s * py
        r = math.hypot(ax - cx0, ay - cy0)
        a0 = math.atan2(ay - cy0, ax - cx0)
        a1 = math.atan2(by - cy0, bx - cx0)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        pts = [a]
        for i in range(1, nseg):
            am = a0 + da * i / nseg
            pts.append(vec(cx0 + r * math.cos(am), cy0 + r * math.sin(am)))
        pts.append(b)
        for p0, p1 in zip(pts, pts[1:]):
            self.track(p0, p1, netname, layer=layer, width=width, locked=locked)

    def true_arc(self, a, b, netname, layer=pcbnew.F_Cu, width=None):
        """Real PCB_ARC between a,b centered near board center. Only safe
        after freerouting is done (its DSN import chokes on arcs)."""
        ax, ay = rel(a)
        bx, by = rel(b)
        mxp, myp = (ax + bx) / 2, (ay + by) / 2
        dx, dy = bx - ax, by - ay
        px, py = -dy, dx
        norm = math.hypot(px, py)
        px, py = px / norm, py / norm
        s = -(mxp * px + myp * py)
        cx0, cy0 = mxp + s * px, myp + s * py
        r = math.hypot(ax - cx0, ay - cy0)
        a0 = math.atan2(ay - cy0, ax - cx0)
        a1 = math.atan2(by - cy0, bx - cx0)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        am = a0 + da / 2
        t = pcbnew.PCB_ARC(self.board)
        t.SetStart(a)
        t.SetMid(vec(cx0 + r * math.cos(am), cy0 + r * math.sin(am)))
        t.SetEnd(b)
        t.SetLayer(layer)
        t.SetWidth(mm(width or self.j["default_track_mm"]))
        t.SetNet(self.net(netname))
        self.board.Add(t)
        return t

    def via(self, pos, netname, locked=True):
        v = pcbnew.PCB_VIA(self.board)
        v.SetPosition(pos if isinstance(pos, pcbnew.VECTOR2I) else vec(*pos))
        v.SetDrill(mm(self.j["via_drill_mm"]))
        v.SetWidth(mm(self.j["via_diameter_mm"]))
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(self.net(netname))
        v.SetLocked(locked)
        v.SetFrontTentingMode(pcbnew.TENTING_MODE_TENTED)
        v.SetBackTentingMode(pcbnew.TENTING_MODE_TENTED)
        self.board.Add(v)
        return v

    @staticmethod
    def in_feet_keepout(x, y):
        """Back-side keepouts for through vias:
        - battery clip feet: |x| 10.2..14.3, |y| < 3.3
        - BOOTSEL button SW1 at the top: |x| < 3.3, y -14.5..-10.3"""
        if abs(y) < 3.3 and 10.2 < abs(x) < 14.3:
            return True
        return False

    def zone(self, layer, netname, poly, priority=0, name=""):
        z = pcbnew.ZONE(self.board)
        z.SetLayer(layer)
        z.SetNet(self.net(netname))
        z.SetAssignedPriority(priority)
        z.SetMinThickness(mm(0.15))
        z.SetLocalClearance(mm(self.j["min_clearance_mm"]))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.25))
        z.SetThermalReliefSpokeWidth(mm(0.3))
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        if name:
            z.SetZoneName(name)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in poly:
            ol.Append(mm(CX + x), mm(CY + y))
        self.board.Add(z)
        return z

    def circle_poly(self, r, n=72, r_inner=None):
        pts = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n))
               for i in range(n)]
        return pts


def wipe(board):
    # Delete (not Remove): Remove leaves ownership dangling on the python
    # proxy side -> heap corruption / segfaults later in the run
    for t in list(board.GetTracks()):
        board.Delete(t)
    for z in list(board.Zones()):
        board.Delete(z)


def pad_of(fp, num):
    for p in fp.Pads():
        if p.GetNumber() == str(num):
            return p
    raise KeyError(f"{fp.GetReference()} pad {num}")


def add_keepouts(board, rt):
    """No-via rule areas where the battery clip feet and BOOTSEL button sit."""
    rects = [(-14.3, -3.3, -10.2, 3.3), (10.2, -3.3, 14.3, 3.3)]  # clip feet
    for x0, y0, x1, y1 in rects:
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowVias(True)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowCopperPour(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetLayer(pcbnew.B_Cu)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            ol.Append(mm(CX + x), mm(CY + y))
        board.Add(z)


def beautify_led_chain(board, rt, fps, n_leds):
    """Replace freerouting's LED-chain segments with clean constant-radius
    arcs — per hop, only when the arc path is clear of foreign copper
    (freerouting may have parked e.g. a VLED fanout via in the corridor)."""
    import finish as fin
    obs = fin.Obstacles(board)
    kept = 0
    for i in range(n_leds - 1):
        net = f"LED_D{i+1}"
        a = pad_of(fps[f"LED{i+1}"], 4).GetPosition()   # DO
        b = pad_of(fps[f"LED{i+2}"], 1).GetPosition()   # DI
        ar, br = rel(a), rel(b)
        # sample the arc corridor: treat all LED_D* as friendly
        n = 12
        clear = True
        for k in range(n + 1):
            x = ar[0] + (br[0] - ar[0]) * k / n
            y = ar[1] + (br[1] - ar[1]) * k / n
            for it in obs.near_items(x, y):
                inet = it[2]
                if inet.startswith("LED_D"):
                    continue
                if it[0] == "via":
                    if math.hypot(it[3] - x, it[4] - y) < 0.13 + 0.075 + it[5]:
                        clear = False
                elif it[0] == "seg" and it[1] == pcbnew.F_Cu:
                    if fin.seg_pt_dist(it[3], it[4], (x, y)) < 0.13 + 0.075 + it[5]:
                        clear = False
                elif it[0] == "padc":
                    th_pad = it[6]
                    if (th_pad or pcbnew.F_Cu in it[1]) and \
                            fin.seg_pt_dist(it[3], it[4], (x, y)) < 0.13 + 0.075 + it[5]:
                        clear = False
            if not clear:
                break
        if not clear:
            kept += 1
            continue
        for t in list(board.GetTracks()):
            if t.GetNetname() == net:
                board.Delete(t)
        rt.true_arc(a, b, net)
    if kept:
        print(f"beautify: kept freerouting wiring on {kept} hops")


def post_routes(board, rt, fps):
    """No deterministic wiring: freerouting owns all wires. Topology for the
    tricky spots is channeled via pre-placed vias in main()."""
    pass


def main():
    no_freeroute = "--no-freeroute" in sys.argv
    design = load_design()
    board = pcbnew.LoadBoard(str(PCB))
    wipe(board)
    rt = Router(board, design)
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    n_leds = design["leds"]["count"]
    r_board = design["board"]["diameter_mm"] / 2
    r_led = r_board - design["leds"]["ring_margin_mm"]

    # Scripted structure is deliberately minimal: inner-layer planes and
    # keepouts only. Freerouting v2 hangs on any pre-existing wire segments,
    # so it owns ALL wires and fanout vias; planes give it the power nets.
    add_keepouts(board, rt)
    # A few strategic plane-access vias (bare vias are safe pre-freerouting;
    # wires are not). They give freerouting cheap 3V3 access in the dense
    # left/right clusters.
    # NB: no through vias possible for r<4.4 — the battery clip's 8mm GND
    # contact pad covers the back there.
    for pos in ((-5.9, -1.2), (6.2, 2.6), (0.9, 4.1), (0.05, 3.95)):
        rt.via(pos, "3V3")
    # channel the HRO connector's interleaved duplicate-pad joins through
    # the front layer: DM hops inboard of the pad row, DP outboard
    for pos in ((-0.75, -13.55), (0.25, -13.55)):
        rt.via(pos, "USB_DM_C")
    for pos in ((-0.25, -15.0), (0.75, -15.0)):
        rt.via(pos, "USB_DP_C")
    from outline import outline_points, offset_polygon
    margin = design["leds"]["ring_margin_mm"]
    outer = outline_points(design, 100)
    zp = rt.zone(pcbnew.In1_Cu, "GND", outer, name="gnd_plane")
    zp.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z = rt.zone(pcbnew.In2_Cu, "VLED", outer, priority=1, name="vled_annulus")
    hole = offset_polygon(design, margin + 3.0, 80)
    ol = z.Outline()
    ol.NewHole()
    for x, y in hole:
        ol.Append(mm(CX + x), mm(CY + y), 0, 0)
    # circle disc; overlaps the narrow tip part of the VLED hole, where its
    # higher priority carves VLED back automatically
    rt.zone(pcbnew.In2_Cu, "3V3", rt.circle_poly(9.55), priority=2,
            name="p3v3_disc")
    pcbnew.SaveBoard(str(PCB), board)

    # ---------- freerouting ----------
    if not no_freeroute:
        dsn = ROOT / "out" / "earring.dsn"
        ses = ROOT / "out" / "earring.ses"
        ses.unlink(missing_ok=True)
        if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
            print("DSN export failed")
            sys.exit(1)
        cmd = ["java", "-jar", str(JAR), "-de", str(dsn), "-do", str(ses),
               "-mp", "40", "--gui.enabled=false"]
        print("running freerouting…")
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if not ses.exists():
            print(r.stdout[-3000:])
            print(r.stderr[-2000:])
            print("freerouting produced no SES")
            sys.exit(1)
        board = pcbnew.LoadBoard(str(PCB))
        if not pcbnew.ImportSpecctraSES(board, str(ses)):
            print("SES import failed")
            sys.exit(1)
        rt = Router(board, design)
        fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
        # freerouting emits zero-length artifact wires at plane boundaries
        zl = 0
        for t in list(board.GetTracks()):
            if not isinstance(t, pcbnew.PCB_VIA) and t.GetLength() == 0:
                board.Delete(t)
                zl += 1
        if zl:
            print(f"removed {zl} zero-length wires")
        # NOTE: freerouting places some signal wires on the plane layers;
        # the zone filler pours around them. Acceptable for this board.
        if "--no-beautify" not in sys.argv:
            beautify_led_chain(board, rt, fps, n_leds)
        post_routes(board, rt, fps)

    # ---------- outer pours (post-route: as DSN planes they stall freerouting) ----------
    from outline import offset_polygon as _offp
    rt2 = Router(board, design)
    _pour = _offp(design, 0.3, 80)
    zf = rt2.zone(pcbnew.F_Cu, "GND", _pour, name="gnd_front")
    zb = rt2.zone(pcbnew.B_Cu, "GND", _pour, name="gnd_back")
    zf.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    zb.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)

    # ---------- fill + report ----------
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    board.BuildConnectivity()
    unconnected = board.GetConnectivity().GetUnconnectedCount(True)
    print(f"routing done; unconnected: {unconnected}")


if __name__ == "__main__":
    main()
