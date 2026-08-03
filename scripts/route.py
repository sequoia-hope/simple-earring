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
    # NPTH holes (e.g. SW2's locating pegs) carry no copper, so the
    # Obstacles model skips them — but an arc through one is a DRC error
    npth = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                px, py = rel(p.GetPosition())
                npth.append((px, py, to_mm(p.GetDrillSize().x) / 2))
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
            for hx, hy, hr in npth:
                if math.hypot(hx - x, hy - y) < hr + 0.075 + 0.3:
                    clear = False
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


def add_ring_stubs(board, rt):
    """Stub U1's DVDD pins into the transplanted under-chip 1V1 square and
    the IOVDD/QSPI_IOVDD pins into the 3V3 ring. The official board feeds
    its rings through B.Cu traces + its base pour; on this board the moat
    between the EP and the pin ring is freerouting territory, so each stub
    is gated against the routed copper and silently skipped when blocked
    (the rings are redundant copper, not the primary connection)."""
    import finish as fin
    obs = fin.Obstacles(board)
    u1 = None
    for fp in board.GetFootprints():
        if fp.GetReference() == "U1":
            u1 = fp
    # pad number -> stub endpoint inside the ring copper (board-frame mm)
    STUBS = {
        "6":  (2.05, 0.30), "23": (0.00, -2.55), "39": (-2.05, -0.10),
        "1":  (2.50, 2.30), "11": (2.50, -1.70), "20": (1.20, -3.10),
        "30": (-2.55, -3.05), "38": (-2.50, -0.50), "45": (-2.50, 2.30),
        "53": (0.00, 2.10), "54": (0.40, 2.10),
    }
    added = skipped = 0
    for p in u1.Pads():
        num = p.GetNumber()
        if num not in STUBS:
            continue
        px, py = rel(p.GetPosition())
        # start just inside the pad's inner end (pads are 0.88 long)
        sx = px - math.copysign(0.34, px) if abs(px) > 3 else px
        sy = py - math.copysign(0.34, py) if abs(px) <= 3 else py
        end = STUBS[num]
        if obs.clear_seg((sx, sy), end, pcbnew.F_Cu, p.GetNetname(),
                         0.127 + 0.10):
            rt.track((sx, sy), end, p.GetNetname(), width=0.2)
            added += 1
        else:
            skipped += 1
    print(f"power-ring stubs: {added} added, {skipped} blocked")


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
    # (bottom-center pair kept at r>4.4: inside that radius the clip's 8mm
    # back pad eats the via holes — they only survived DRC before because
    # they went unused and were dropped as dangling)
    # ((-1.2,-8.3): the crystal-pocket decaps' 3V3 feed — SW1's move to
    # top-center displaced the corridor they used to tap)
    for pos in ((-5.9, -1.2), (6.2, 2.6), (0.9, 5.0), (-0.6, 4.5),
                (-1.2, -8.3)):
        rt.via(pos, "3V3")
    # VREG single-point ground return: two vias INSIDE the transplanted
    # local GND pour, at the official minimal design's spots (rotated);
    # separate dedicated via for CFILT's GND
    for pos in ((-3.10, 4.40), (-3.10, 5.00)):
        rt.via(pos, "GND")
    rt.via((-4.65, 3.20), "GND")
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
    # NB: do NOT put a rule area over the In2 disc to stop wire crossings —
    # freerouting treats the DSN keepout as a hard obstacle and loses the
    # whole center region (18 unrouted vs the usual 6). Disc splits are
    # instead healed post-route by stitch_p3v3_islands() in finish.py.
    # C30's VLED plane access: via-in-pad (tented) — the only tip-left spot
    # where a through-via clears SW2's back-side copper
    rt.via(rel(pad_of(fps["C30"], 1).GetPosition()), "VLED")
    # LED1/LED2 VCC fanout: the tip-left VLED pocket is hemmed in by the
    # LED chain (front) and SW2 (back); freerouting strands it on most
    # seeds. One via per LED, spot scanned against all static copper —
    # pre-route vias can't conflict with wires (freerouting routes around
    # them), only pads/holes/edge matter.
    def safe_via_spot(cx, cy):
        pads = [(p, fp) for fp in board.GetFootprints() for p in fp.Pads()]
        for r in (0.7, 0.9, 1.1):
            for k in range(16):
                ang = math.pi * 2 * k / 16
                x, y = cx + r * math.cos(ang), cy + r * math.sin(ang)
                if math.hypot(x, y) < 4.6:
                    continue  # battery clip back pad
                # inside the outline with margin, and within the VLED band?
                from outline import half_width_at
                if abs(x) > half_width_at(load_design(), y) - 0.45:
                    continue
                if abs(x) < half_width_at(load_design(), y) - 4.5:
                    continue
                ok = True
                for p, fp in pads:
                    pp = p.GetPosition()
                    d = math.hypot(to_mm(pp.x) - 100 - x,
                                   to_mm(pp.y) - 100 - y)
                    sz = p.GetSize(pcbnew.F_Cu)
                    half = math.hypot(to_mm(sz.x), to_mm(sz.y)) / 2
                    need = 0.55 if p.GetNetname() != "VLED" else 0.0
                    if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                        need = 0.75  # hole-to-hole
                    if d < half + need:
                        ok = False
                        break
                if ok:
                    return (x, y)
        return None
    for ref in ("LED1", "LED2"):
        px, py = rel(pad_of(fps[ref], 2).GetPosition())
        spot = safe_via_spot(px, py)
        if spot:
            rt.via(spot, "VLED")
        else:
            print(f"WARNING: no safe VLED via spot near {ref}")
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
    add_ring_stubs(board, rt2)

    # RP2350 ds §6.3.8: cut copper under the inductor (F.Cu) and cut the
    # layer-2 plane under the inductor + VREG_LX node (In1). Added post-route
    # so the DSN never sees them (freerouting treats keepouts as obstacles).
    def pour_keepout(layer, x0, y0, x1, y1):
        z = pcbnew.ZONE(board)
        z.SetIsRuleArea(True)
        z.SetDoNotAllowCopperPour(True)
        z.SetDoNotAllowVias(False)
        z.SetDoNotAllowTracks(False)
        z.SetDoNotAllowPads(False)
        z.SetDoNotAllowFootprints(False)
        z.SetLayer(layer)
        ol = z.Outline()
        ol.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            ol.Append(mm(CX + x), mm(CY + y))
        board.Add(z)

    pour_keepout(pcbnew.In1_Cu, -3.35, 5.65, -0.65, 8.00)  # In1 under L1
    pour_keepout(pcbnew.In1_Cu, -2.60, 2.60, -1.80, 5.65)  # In1 under LX
    # (no F.Cu rule-area under L1 any more: the transplanted 1V1/LX pours
    # own that area, and gnd_front is kept out by the cluster hole below)
    _pour = _offp(design, 0.3, 80)
    zf = rt2.zone(pcbnew.F_Cu, "GND", _pour, name="gnd_front")
    zb = rt2.zone(pcbnew.B_Cu, "GND", _pour, name="gnd_back")
    zf.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    zb.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    # gnd_front stays out of the VREG cluster entirely (the official board
    # cuts its base pour around the cluster the same way): the local GND
    # pour + its return vias are the ONLY front-side GND there, keeping the
    # single-point return and no GND slivers under L1 / between the pours.
    ol = zf.Outline()
    ol.NewHole()
    for x, y in ((-3.75, 2.30), (-0.85, 2.30), (-0.85, 8.20), (-3.75, 8.20)):
        ol.Append(mm(CX + x), mm(CY + y), 0, 0)

    # ---------- VREG pours transplanted from the official minimal design ----
    # Polygons lifted verbatim from RPI-RP2350A-MINIMAL_R4-S1.kicad_pcb
    # (KiCad-10 file parsed as sexpr text; chip-frame mm, official U1 rot=0).
    # Our U1 is the official chip rotated 180°, so map (x,y)->(-x, U1Y-y).
    # Relative priorities preserved from the official board; all sit above
    # gnd_front(0). The caps MUST sit at x=-2.00 (place.py) or the 0.3mm LX
    # finger threading their pad gap pinches below the 0.15 min fill width.
    U1Y = -0.5
    OFFICIAL_POURS = [
        # under-chip 3V3 ring (between the 1V1 square and the pin ring)
        ("3V3", 1, [(2.8, 2.8), (-2.8, 2.8), (-2.8, -2.8), (2.8, -2.8)]),
        # under-chip 1V1 square (ring around the EP once GND clears it)
        ("VDD_CORE", 3, [(2.2, 2.2), (-2.2, 2.2), (-2.2, -2.2), (2.2, -2.2)]),
        # local GND return: PGND pin 47 + CIN/COUT GND pads + return vias
        ("GND", 4, [(2.3, -3.15), (2.3, -4.85), (2.45, -4.85), (2.45, -5.3),
                    (2.3, -5.3), (2.3, -5.8), (3.1, -5.8), (3.4, -5.5),
                    (3.4, -4.75), (2.5, -3.85), (2.5, -3.15)]),
        # LX: pin 48 -> 0.3mm finger between the cap pad columns -> wide
        # column into L1 pad 2
        ("VREG_LX", 5, [(1.9, -3.15), (1.9, -3.95), (1.85, -4.0),
                        (1.85, -6.15), (2.35, -6.65), (2.35, -8.05),
                        (3.05, -8.05), (3.05, -6.35), (2.75, -6.05),
                        (2.3, -6.05), (2.15, -5.9), (2.15, -4.0),
                        (2.1, -3.95), (2.1, -3.15)]),
        # 1V1 switcher pour: L1 pad 1 + COUT hot pad + FB landing lobe
        ("VDD_CORE", 6, [(1.65, -5.3), (1.65, -6.675), (1.65, -8.05),
                         (0.95, -8.05), (0.95, -6.2), (1.25, -5.9),
                         (1.25, -5.75), (1.05, -5.75), (0.7, -6.1),
                         (0.5, -6.1), (0.2, -5.8), (0.2, -5.2), (0.5, -4.9),
                         (1.0, -4.9), (1.0, -5.1), (1.55, -5.1),
                         (1.55, -5.3)]),
        # 3V3 feed finger: VREG_VIN pin 49 -> CIN hot pad (also merges with
        # the under-chip 3V3 ring at its tip)
        ("3V3", 7, [(1.5, -2.7), (1.5, -4.05), (1.25, -4.3), (1.25, -4.85),
                    (1.7, -4.85), (1.7, -2.7)]),
    ]
    for netname, prio, poly in OFFICIAL_POURS:
        pts = [(-x, U1Y - y) for x, y in poly]
        z = rt2.zone(pcbnew.F_Cu, netname, pts, priority=prio,
                     name=f"vreg_{netname.lower()}_{prio}")
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)  # official: solid

    # ---------- fill + report ----------
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(str(PCB), board)
    board.BuildConnectivity()
    unconnected = board.GetConnectivity().GetUnconnectedCount(True)
    print(f"routing done; unconnected: {unconnected}")


if __name__ == "__main__":
    main()
