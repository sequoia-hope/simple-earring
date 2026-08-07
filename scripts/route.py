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
from circuit import LED_PIN, load_design  # noqa: E402

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
        (The SW1 range this used to also list was never implemented, and
        was stale anyway: SW1 is now the smaller SKRPAME010 at y=-11.2,
        courtyard |x|<2.10, y -12.8..-9.6.)"""
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
        a = pad_of(fps[f"LED{i+1}"], LED_PIN["DO"]).GetPosition()
        b = pad_of(fps[f"LED{i+2}"], LED_PIN["DI"]).GetPosition()
        ar, br = rel(a), rel(b)
        # sample the TRUE arc corridor (same geometry as true_arc below):
        # at ring radius a chord sample was close enough, but interior hops
        # bulge up to a few mm off the chord and sweep the r~9.4 annulus —
        # a chord sample let an arc short a VBUS trace + R9's pad (seen
        # live). Treat all LED_D* as friendly.
        mxp, myp = (ar[0] + br[0]) / 2, (ar[1] + br[1]) / 2
        dxc, dyc = br[0] - ar[0], br[1] - ar[1]
        pxc, pyc = -dyc, dxc
        pnorm = math.hypot(pxc, pyc) or 1e-9
        pxc, pyc = pxc / pnorm, pyc / pnorm
        sc = -(mxp * pxc + myp * pyc)
        cx0, cy0 = mxp + sc * pxc, myp + sc * pyc
        rr = math.hypot(ar[0] - cx0, ar[1] - cy0)
        a0 = math.atan2(ar[1] - cy0, ar[0] - cx0)
        a1 = math.atan2(br[1] - cy0, br[0] - cx0)
        da = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
        n = max(12, int(abs(da) * rr / 0.3))
        clear = True
        for k in range(n + 1):
            am = a0 + da * k / n
            x = cx0 + rr * math.cos(am)
            y = cy0 + rr * math.sin(am)
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
    # ((-0.35,4.5) not (-0.6,4.5): shifted right so the locked FB link can
    # enter the switcher pour's lobe at x=-1.0 with 0.127 via clearance)
    # ((-5.85,-1.60) not (-5.9,-1.2): the QSPI flash U7 (RP2350A revision)
    # took the pocket north of it and its pad-5 tip lands 0.07 from the old
    # spot. Grid-scanned (0.05mm, all pads both sides + locked tracks +
    # vias + 3V3-disc/clip-pad radii): this is the nearest legal spot, 0.40
    # away. Re-scan rather than nudge by eye if anything here moves.
    # ((-4.25,-7.55) not (-1.2,-8.3): the Aug 5 2026 ABM8-272-T3 swap grew
    # the crystal to a 3225 and moved Y1 to (0,-8.02), which swallowed the
    # old spot — it lands inside Y1's courtyard, ON its GND pad 2. Re-scanned
    # with safe_via_spot()'s constraint model rather than nudged by eye, as
    # the note below says to. The nearest legal spot (-2.42,-7.86) clears by
    # only 0.02 against Y1 pad 3, so this takes the best-clearance spot in
    # the pocket instead: 0.96mm margin, and its tightest neighbour is C8
    # pad 1 — which is 3V3 itself, i.e. it sits right on the decap it feeds.)
    for pos in ((-5.85, -1.60), (6.2, 2.6), (0.9, 5.0), (-0.35, 4.5),
                (-4.25, -7.55)):
        rt.via(pos, "3V3")
    # VREG single-point ground return: two vias INSIDE the transplanted
    # local GND pour, at the official minimal design's spots (rotated);
    # separate dedicated via for CFILT's GND
    for pos in ((-3.10, 4.40), (-3.10, 5.00)):
        rt.via(pos, "GND")
    rt.via((-4.65, 3.20), "GND")
    # canonical FB link: pin 50 -> the switcher pour's FB landing lobe
    # (the lobe stops 1mm short of the FB pad on the official board too;
    # without this link freerouting can leave the cluster copper and the
    # pin-ring VDD_CORE as two fragments whose closest approach is mid-air
    # over U2 — no candidate the finisher can act on). Geometry is exact
    # against the 0.127 rule: out of pad 50 dead-center of the pin 49/51
    # gap (pad edges -1.5/-0.9 -> 0.225 each side), jog right at y=3.66
    # (0.205 above the pad tips, 0.15 under C11 pad1's corner at
    # (-1.25,3.885)), up at x=-1.00 (0.175 off C11 pad1) into the lobe's
    # bottom-left corner (-1.0,4.4). The 3V3 finger pour it grazes is
    # filled post-route and necks around this track on its own. A stray
    # clearance violation here is fatal: freerouting cannot rip up locked
    # wiring and burns its whole 900s budget trying (seen live), so
    # re-audit pads AND pre-placed vias before moving any coordinate.
    # (C leg at -1.02, not -1.00: buys the USB_DM escape diagonal its
    # 0.277 corner clearance; C11 pad1 gap is still 0.155)
    for a, b in (((-1.20, 3.30), (-1.20, 3.66)),
                 ((-1.20, 3.66), (-1.02, 3.66)),
                 ((-1.02, 3.66), (-1.02, 4.44))):
        rt.track(a, b, "VDD_CORE", width=0.15)
    # channel the HRO connector's interleaved duplicate-pad joins through
    # the front layer: DM hops inboard of the pad row, DP outboard
    for pos in ((-0.75, -13.55), (0.25, -13.55)):
        rt.via(pos, "USB_C_DN")
    for pos in ((-0.25, -15.0), (0.75, -15.0)):
        rt.via(pos, "USB_C_DP")
    # ---------- USB differential pair (canonical, locked) ----------
    # J1 -> U5 (flow-through ESD) -> down the back WEST of the battery
    # clip's 8x8 back pad, around its SW corner with concentric-C parity
    # (outer lane always turns onto the farther rail so the pair never
    # crosses itself) -> via pair below R6/R7 -> up to their pad 1, DP
    # threading the 0.48mm R7.1/R7.2 gap at x=2.1. Keeps DP/DM paired at
    # 0.30mm centers for the shared run and, critically, off the inner
    # layers: freerouting used to snake both lines through In1/In2,
    # slotting the GND plane and splitting the 3V3 disc. The west side is
    # chosen because an east-side run walls off SWCLK's back-side test
    # pad, VBUS's route to the charger and BOOTSEL (seen live: 6/6 seeds
    # failed); west only PWR_EN crosses, with an easy front hop. The
    # verticals jog west around the GND via at (-4.65,3.2). Every
    # segment, via and cross-net pairing is verified numerically against
    # all pads (rect models), holes, pre-placed vias and the other locked
    # links, including segment crossings — re-run the checker on ANY
    # coordinate change: a locked-wire clearance violation makes
    # freerouting burn its whole 900s budget.
    # Topology: J1's pin order puts DM's duplicate pads outside DP's at
    # the connector, while R7 (DM) sits above R6 (DP) — one pair crossing
    # is unavoidable. It happens on the west side as a short F.Cu hop
    # (vias at (-4.34,-9.40)/(-5.40,-8.75), a zone that is empty on F):
    # DP crosses over DM's rail, so DM rides outer-north/inner-south and
    # the escapes stay planar. VBUS's ties would be walled in by the DP
    # tip bypass, so it gets a locked link too: via-in-pad on U5.5 (same
    # trick as C30) and an F.Cu trunk over U5's body joining both ties.
    USB_PAIR = {
        "USB_C_DN": [
            # J1's pad row + tie pads + shell legs form an unbroken wall
            # across the back at y -14.8..-13.4 — the ONLY legal vertical
            # corridors are through your own net's pads. DM rises through
            # B7's column, DP through B6's.
            ("F", (-0.75, -13.55), (0.25, -13.55)),  # duplicate-pad join
            ("B", (-0.75, -13.55), (-0.75, -12.60)),  # rise through B7
            ("B", (-0.75, -12.60), (-0.85, -12.35)),
            ("B", (-0.85, -12.35), (-0.85, -12.04)),  # into U5.3
            ("B", (0.85, -12.04), (-0.85, -12.04)),   # flow-through to U5.4
            ("B", (-0.85, -12.35), (-4.75, -12.35)),  # west, outer rail
            ("B", (-4.75, -12.35), (-4.75, -8.30)),
            ("B", (-4.75, -8.30), (-5.10, -7.95)),    # inner after the cross
            ("B", (-5.10, -7.95), (-5.10, 6.55)),     # past GND via (dx .45)
            ("B", (-5.10, 6.55), (2.45, 6.55)),       # south, upper rail
            ("B", (2.45, 6.55), (2.45, 7.05)),        # drop to via
            ("F", (2.45, 7.05), (2.10, 6.55)),
            ("F", (2.10, 6.55), (2.10, 5.35)),        # R7.1/R6.1 gap
            ("F", (2.10, 5.35), (1.80, 5.05)),
            ("F", (1.80, 5.05), (1.59, 4.75)),        # R7 pad 1 (upper)
        ],
        "USB_C_DP": [
            ("B", (-0.25, -14.60), (-0.25, -15.00)),  # pad stubs to vias
            ("B", (0.75, -14.60), (0.75, -15.00)),
            ("F", (-0.25, -15.00), (0.75, -15.00)),   # duplicate-pad join
            ("B", (0.75, -15.00), (0.75, -13.00)),    # rise through B6
            ("B", (0.75, -13.00), (1.62, -12.55)),
            ("B", (1.62, -12.55), (1.62, -11.10)),    # east of U5.4/U5.5
            ("B", (1.62, -11.10), (1.10, -10.96)),    # into U5.6
            ("B", (1.10, -10.96), (-0.85, -10.96)),   # flow-through to U5.1
            ("B", (-0.85, -10.96), (-4.45, -10.96)),  # west, inner rail
            ("B", (-4.45, -10.96), (-4.34, -10.80)),
            ("B", (-4.34, -10.80), (-4.34, -9.40)),   # to crossing via
            ("F", (-4.34, -9.40), (-5.40, -8.75)),    # F hop over DM's rail
            ("B", (-5.40, -8.75), (-5.40, 6.85)),     # outer after the cross
            ("B", (-5.40, 6.85), (1.05, 6.85)),       # south, lower rail
            ("B", (1.05, 6.85), (1.05, 7.05)),        # drop to via
            ("F", (1.05, 7.05), (1.45, 6.35)),
            ("F", (1.45, 6.35), (1.59, 5.95)),        # R6 pad 1 (lower)
        ],
    }
    # NB: do NOT lock the pin 51/52 escapes (USB_DM/USB_DP). Fixed wires
    # that START on U1's pads hang freerouting v2 before pass 1 (bisected
    # via DSN text-editing: removing only those two nets' wires from an
    # otherwise identical DSN un-hangs it). With R7 (DM) on the upper row
    # the escapes are easy for freerouting anyway — that was the point of
    # the R6/R7 swap.
    # (VBUS's F.Cu trunk is laid POST-route — see below. Pre-placing
    # those tracks makes freerouting v2.2.4 crash at SES-write time and
    # silently restart its whole job every ~2 min until the 900s timeout
    # (bisected with probe DSNs: with the tracks removed and only the
    # three via-in-pads kept, the SES writes fine). The vias go in now
    # so nothing else takes their spots.)
    for net, segs in USB_PAIR.items():
        for layer, a, bpt in segs:
            ly = pcbnew.F_Cu if layer == "F" else pcbnew.B_Cu
            rt.track(a, bpt, net, layer=ly, width=0.15)
    rt.via((2.45, 7.05), "USB_C_DN")
    rt.via((1.05, 7.05), "USB_C_DP")
    rt.via((-4.34, -9.40), "USB_C_DP")
    rt.via((-5.40, -8.75), "USB_C_DP")
    rt.via((-2.35, -13.45), "VBUS")  # via-in-pad on tie A4B9
    rt.via((0.92, -11.50), "VBUS")   # via-in-pad on U5.5 (tented)
    rt.via((2.20, -12.99), "VBUS")   # SE of tie B4A9 — Sequoia moved it
    # off-pad (Aug 7) to clear the tip; the tie pad still joins the trunk
    from outline import outline_points, offset_polygon
    margin = design["leds"]["ring_margin_mm"]
    outer = outline_points(design, 100)
    n_layers = design["board"]["layers"]
    zp = rt.zone(pcbnew.In1_Cu, "GND", outer, name="gnd_plane")
    zp.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    z = rt.zone(pcbnew.In2_Cu, "VLED", outer, priority=1, name="vled_annulus")
    if n_layers >= 6:
        hole = offset_polygon(design, margin + 3.0, 80)
        disc_r = 9.55
    else:
        # 4-layer: there is no In4 VLED plane, so In2's annulus is the ONLY
        # plane VLED. Pull its hole in to a circle just inside the interior
        # LED octagon (VCC pads at r 9.64-9.79, measured) so those eight
        # LEDs keep a plane drop, and shrink the 3V3 disc to clear it.
        # The inner VLED consumers below r 9.3 (U4, C20, C68-C74 at
        # r 6.6-8.6) fall back to routed traces either way.
        hole = rt.circle_poly(9.35)
        disc_r = 9.15
    ol = z.Outline()
    ol.NewHole()
    for x, y in hole:
        ol.Append(mm(CX + x), mm(CY + y), 0, 0)
    # circle disc; overlaps the narrow tip part of the VLED hole, where its
    # higher priority carves VLED back automatically
    rt.zone(pcbnew.In2_Cu, "3V3", rt.circle_poly(disc_r), priority=2,
            name="p3v3_disc")
    # In4: solid VLED plane (6-layer only). The In2 interior is the 3V3
    # disc, so the interior LED ring's VCC fanout drops through to In4
    # instead — through vias reach it anywhere clear of the clip back pad
    # (r>4.6).
    if n_layers >= 6:
        rt.zone(pcbnew.In4_Cu, "VLED", outer, name="vled_plane")
    # In3: mostly freerouting's interior signal layer, EXCEPT a 3V3 pour
    # under the back-east IMU cluster: its nine 3V3 pads sit at r 11-14
    # while the nearest 3V3 copper (In2 disc) ends at r 9.55 — without
    # this, freerouting strands the whole cluster (seen live: 18 unrouted
    # plateau, all east-pocket nets). The pour overlaps the disc in plan;
    # the pre-placed via below bridges the two layers.
    # (keep this polygon in sync with finish.py E3V3_POUR; the south lobe
    # reaches R15's 3V3 pad at (6.3,-13.86) while keeping 1.4mm from the
    # J1 shell leg hole at (4.33,-14.88))
    # (4-layer has no In3: the cluster's 3V3 has to be routed as ordinary
    # B.Cu traces from the disc. That is one of the two things the 4-layer
    # attempt is testing — see docs/HANDOFF.md Task 5.)
    if n_layers >= 6:
        from finish import E3V3_POUR_PTS
        rt.zone(pcbnew.In3_Cu, "3V3", E3V3_POUR_PTS, name="p3v3_east")
        # bridge via: inside both the In2 disc (r<9.55) and the In3 east
        # pour; front side clear of LED45/C20/C13 pads (checked with the
        # pre-route DRC pass), back side r>4.6 and off the clip feet
        rt.via((6.6, -5.6), "3V3")
    # Right-column IOVDD decaps (C2/C4/C6/C7): dedicated 3V3 disc vias
    # 0.75mm east of each 3V3 pad. Their old fanout ran laterally along
    # the escape corridor — the IMU-signal escapes below now own those
    # lanes, and a first attempt at a single x=5.6 via column walled the
    # caps off instead (seen live: every right-column decap 3V3 pad
    # stranded). Self-served pads need no lateral lanes at all.
    # (each via sits beside its cap's 3V3 pad, ring clear of the escape
    # gaps; y values track the right-column decap positions in place.py.
    # C7 lives out east by the (6.2,2.6) 3V3 via and needs no via of its
    # own.)
    for pos in ((5.45, -3.45), (5.55, -1.0), (5.55, 1.35)):
        rt.via(pos, "3V3")
    # Channel vias for the IMU signals + LED_EN: the U1 right-side escape
    # is only ~2mm of clear F.Cu before the decap column; the long haul to
    # the back-east cluster must happen on B (open over the cell region).
    # Without a committed layer change freerouting strands all four nets
    # (seen live: deterministic 16-unrouted plateau). Same trick as the
    # USB duplicate-pad joins. Staggered east of the decap-via column so
    # the escapes thread the gaps between the 3V3 vias; all spots r>4.6,
    # north of the In3 pour (y>-4.8) and DRC-verified pre-route.
    # Gap plan (right column, caps at -3.6/-1.2/+1.2) — every passage has
    # exactly ONE user, with disjoint runs in the single-lane pin-tip
    # corridor: LED_EN (pin3, y1.5) north of C6; SDA (pin9, y-0.9) the
    # middle gap; INT1 (pin12, y-2.1) the lower gap; SCL (pin15, y-3.3)
    # the south passage between C2 and C13.
    rt.via((6.3, -0.75), "IMU_SDA")
    rt.via((5.15, -5.7), "IMU_SCL")
    rt.via((5.55, -2.35), "IMU_INT1")
    rt.via((7.35, -2.35), "LED_EN")
    # R14 (SDA pull-up) 3V3 pad: via-in-pad into the In3 pour's south
    # lobe (tented — C30's VLED via-in-pad is the precedent). The pad
    # sits deep in the tip lobe where no scanned adjacent via spot
    # clears R10's pads, the J1 leg keepout and the front LED chain
    # simultaneously (seen live as the last stuck edge, 6/6 seeds).
    rt.via(rel(pad_of(fps["R14"], 2).GetPosition()), "3V3")
    # NB: no channel vias for the USB_DM/DP escapes. The escapes' front
    # loop (DM upper row, DP looping east around R6/R7) only failed when
    # BOOTSEL's route to a back-side R3 squatted the loop lane — R3 is
    # back on the front for exactly that reason. Via pairs for DM/DP were
    # tried and are UNFIXABLE: the pin order (51 west of 52) vs any
    # legal via spots forces a same-layer crossing (the only west via
    # slot at r>4.45 belongs to the (-0.35,4.5) 3V3 via).
    # SWDIO to TP3 (back lower-left shoulder): the locked USB-pair rails
    # at x -5.1/-5.4 wall the west back from y -8 to +6.9, so the wire
    # must cross to B WEST of them — commit that with a via left of the
    # chip (TP3's D1-era shoulder move put it past freerouting's patience)
    rt.via((-6.0, -3.1), "SWDIO")
    # SWCLK to TP2 (back east shoulder): same story on the east — the
    # IMU cluster + pour traffic put the long haul past freerouting's
    # plateau; commit the B transition NE of the chip corner
    rt.via((5.3, -4.6), "SWCLK")
    # CHRG_DONE (U1 pin 42, west column +y end -> U2 pin 6): the only
    # charger-status pin with a free escape — the NE corner passage fits
    # two tracks and LED_EN + CHRG own them (pin-4/pin-16 attempts both
    # plateaued). Exit west through the C5/C22 window (VBSENSE's lane
    # stays north of y1.5), cross on In3 (empty in the +y half), pop up
    # NE of the cluster at (7.8,6.6), OUTSIDE the beautify annulus
    # (r10.23+0.2 > 9.76): the hop drops into the 0.64mm U2-C16 lane
    # from the NORTH (center x 7.05-7.29 legal) and enters pad 6 from
    # the east between pins 5/7. Two dead ends, both seen live 6/6:
    # (5.6,6.6) NW of U2 — pin-5 pad + EP wall that approach and the
    # thrash strands LED_EN/RUN/IMU_SDA; (7.0,3.7) south — freerouting
    # self-blocks the lane's south half with C16.2's GND fanout via at
    # (7.45,4.84) (plus CHRG's own B-transition at (6.8,4.75)). The
    # lane's NORTH half has no via-worthy pads, so it stays open. Both
    # spots r>4.6, >=0.25 to U2/C16 pads, >2mm from the octagon LEDs.
    rt.via((-4.6, 1.35), "CHRG_DONE")
    rt.via((7.8, 6.6), "CHRG_DONE")
    # CHRG (U1 pin 31 -> U2 pin 7): private SW exit. East-side homes
    # are over capacity (29/29 attempts stranded a rotating east net)
    # and pairing CHRG into CHRG_DONE's C5/C22 window jams it (two
    # committed via discs wall the window mouth; the pad-tip corridor
    # is single-lane past pin 42 — seen live as a 5-unc plateau with
    # CHRG_DONE/VBSENSE/USB_DP stranded). Pins 31-36 are all NC, so
    # the lane past their tips down to C1's south corner has no other
    # user. Via at (-4.6,-5.8): 0.225 off the locked USB B rail at
    # x-5.1 (keep CHRG-side vias x >= -4.69), below C1 (courtyard ends
    # y-5.23), well west of the crystal cluster. Then In3 across the
    # center to the landing: via-in-pad dead center in pad 7 (tented;
    # R14.2/C30 precedent), 0.175 clear of pads 6/8.
    rt.via((-4.6, -5.8), "CHRG")
    rt.via((6.5, 4.75), "CHRG")
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
    def safe_via_spot(cx, cy, net="VLED", radii=(0.7, 0.9, 1.1)):
        pads = [(p, fp) for fp in board.GetFootprints() for p in fp.Pads()]
        for r in radii:
            for k in range(16):
                ang = math.pi * 2 * k / 16
                x, y = cx + r * math.cos(ang), cy + r * math.sin(ang)
                if math.hypot(x, y) < 4.6:
                    continue  # battery clip back pad
                from outline import half_width_at
                if abs(x) > half_width_at(load_design(), y) - 0.45:
                    continue
                if net == "VLED":
                    # In4 is a full VLED plane: any through via clear of the
                    # clip pad (r>4.6, checked above) reaches VLED
                    pass
                elif net == "3V3":
                    # inside the In2 3V3 disc (r=9.55)
                    if math.hypot(x, y) > 9.55 - 0.45:
                        continue
                ok = True
                for p, fp in pads:
                    pp = p.GetPosition()
                    d = math.hypot(to_mm(pp.x) - 100 - x,
                                   to_mm(pp.y) - 100 - y)
                    sz = p.GetSize(pcbnew.F_Cu)
                    half = math.hypot(to_mm(sz.x), to_mm(sz.y)) / 2
                    need = 0.55 if p.GetNetname() != net else 0.0
                    if p.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                        need = 0.75  # hole-to-hole
                    if d < half + need:
                        ok = False
                        break
                if ok:
                    return (x, y)
        return None
    # same treatment for the mirror pocket on the right tip straight: at
    # the 2.4mm pitch the finisher deterministically fails to reach the
    # last straight LEDs' VCC pads without a pre-scanned via
    ring = design["leds"].get("ring_count", design["leds"]["count"])
    for ref in ("LED1", "LED2", "LED3",
                f"LED{ring}", f"LED{ring - 1}", f"LED{ring - 2}"):
        px, py = rel(pad_of(fps[ref], LED_PIN["VDD"]).GetPosition())
        spot = safe_via_spot(px, py)
        if spot:
            rt.via(spot, "VLED")
        else:
            print(f"WARNING: no safe VLED via spot near {ref}")
    # U3's (LDO) 3V3 output pin is walled in by C19's GND pad + GND
    # fanout at the 2.4mm-pitch seeds — the finisher finds no candidate,
    # so give it a scanned 3V3-disc via up front
    px, py = rel(pad_of(fps["U3"], 1).GetPosition())
    # radii extended past 1.85: the QSPI flash U7 now fills the pocket
    # south of U3, so the near ring often has no legal spot
    spot = safe_via_spot(px, py, "3V3",
                         radii=(0.7, 0.9, 1.1, 1.35, 1.6, 1.85, 2.15,
                                2.45, 2.75))
    if spot:
        rt.via(spot, "3V3")
    else:
        print("WARNING: no safe 3V3 via spot near U3")
    # C32 (the SW2-shadow bypass cap): no legal via spot exists within
    # 1.85mm — SW2's mount pad and pegs plus the LED3/C30 pads wall in
    # the whole pocket (scan-verified). Tie its VLED pad to C30's locked
    # via-in-pad instead. Waypoints are grid-search-verified against every
    # local pad (half-diagonal disc + 0.127 + track half): worst margin
    # is +0.21mm (C30.2 GND / SW1.1 / J1's shell leg are the binders) —
    # a locked-wire clearance violation makes freerouting burn its whole
    # 900s budget, so re-verify numerically before touching these.
    c30 = rel(pad_of(fps["C30"], 1).GetPosition())
    c32 = rel(pad_of(fps["C32"], 1).GetPosition())
    for a, b in ((c32, (-4.90, -11.60)),
                 ((-4.90, -11.60), (-4.00, -13.20)),
                 ((-4.00, -13.20), c30)):
        rt.track(a, b, "VLED", width=0.15)
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
        # freerouting v2 occasionally live-locks in trace normalization
        # (seen: millions of PolylineTrace.normalize retries on one net
        # until the 900s timeout) — it is nondeterministic, so retry
        r = None
        for fr_try in range(2):
            print("running freerouting…")
            try:
                r = subprocess.run(cmd, capture_output=True, text=True,
                                   timeout=900)
                break
            except subprocess.TimeoutExpired:
                print(f"freerouting timed out (try {fr_try + 1}); retrying")
        if not ses.exists():
            if r is not None:
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

    # VBUS trunk (F.Cu over U5's body, joining the tie-pad via-in-pads to
    # U5.5's): pre-routing these tracks crashes freerouting's SES writer
    # (see the pre-route comment), so they go in here. The corridor is
    # numerically verified against all static copper; the gate only
    # protects against freerouting wires that strayed into it — a blocked
    # seg fails this attempt and the route/finish retry rerolls the seed.
    import finish as fin
    obs2 = fin.Obstacles(board)
    VBUS_TRUNK = [((-2.35, -13.45), (-0.50, -12.40)),
                  ((-0.50, -12.40), (0.92, -11.50)),
                  ((0.92, -11.50), (1.60, -12.20)),
                  ((1.60, -12.20), (2.35, -13.45))]
    vb_blocked = 0
    pw = design["jlcpcb"]["power_track_mm"]
    for a, b2 in VBUS_TRUNK:
        # fat first (power netclass width), thin fallback: the corridor
        # over U5's body was verified for 0.15 — the fat variant only goes
        # in when it clears everything too.
        if obs2.clear_seg(a, b2, pcbnew.F_Cu, "VBUS", 0.127 + pw / 2):
            rt2.track(a, b2, "VBUS", width=pw)
        elif obs2.clear_seg(a, b2, pcbnew.F_Cu, "VBUS", 0.127 + 0.075):
            rt2.track(a, b2, "VBUS", width=0.15)
        else:
            vb_blocked += 1
    if vb_blocked:
        print(f"WARNING: VBUS trunk: {vb_blocked} segs blocked by routed copper")

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
    # In4 VLED plane: same cut under the inductor (far plane, belt+braces)
    pour_keepout(pcbnew.In4_Cu, -3.35, 5.65, -0.65, 8.00)
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
