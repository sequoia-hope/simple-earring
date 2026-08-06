#!/usr/bin/env python3
"""Placement: positions every footprint on the generated board.

Coordinate frame: board center = (100,100)mm sheet coords; +y is DOWN on
screen. "Screen angle" θ: pos = center + r·(cosθ, sinθ), so θ=90 is the
bottom of the board, θ=270 the top.

Layout:
  - USB-C at bottom edge (θ≈90), front
  - LED ring on front periphery, arc avoiding the USB connector
    LEDs rotated 45° (diamond) so DI/DO sit on the ring radius: the data
    chain routes as constant-radius arcs; VCC/GND pads land radially
    inward/outward for via drops to the inner planes.
  - RP2354A front center (rotated so USB pins face the connector)
  - Battery clip back center; BOOTSEL + testpoints on back annulus
"""
import math
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import LED_PIN, build_circuit, load_design  # noqa: E402
from outline import led_path, geometry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
CX, CY = 100.0, 100.0


def mm(v):
    return pcbnew.FromMM(v)


def vec(x, y):
    """center-relative mm -> VECTOR2I"""
    return pcbnew.VECTOR2I(mm(CX + x), mm(CY + y))


def polar(r, theta_deg):
    t = math.radians(theta_deg)
    return (r * math.cos(t), r * math.sin(t))


def place(fp, x, y, rot=0.0, back=False):
    fp.SetPosition(vec(x, y))
    if back and fp.GetLayer() != pcbnew.B_Cu:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    fp.SetOrientationDegrees(rot)
    # keep reference text small & on fab layer conceptually; just shrink
    fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.5), mm(0.5)))
    fp.Reference().SetTextThickness(mm(0.1))
    fp.Reference().SetVisible(False)


def pad_pos(fp, num):
    for p in fp.Pads():
        if p.GetNumber() == str(num):
            return p.GetPosition()
    raise KeyError(num)


def main():
    design = load_design()
    cir = build_circuit(design)
    board = pcbnew.LoadBoard(str(PCB))
    fps = {fp.GetReference(): fp for fp in board.GetFootprints()}
    r_board = design["board"]["diameter_mm"] / 2
    r_led = r_board - design["leds"]["ring_margin_mm"]

    # ---------------- LED chain along the teardrop perimeter ----------------
    margin = design["leds"]["ring_margin_mm"]
    end_y = design["leds"].get("path_end_y", -13.2)
    path = led_path(design, margin, end_y)
    n = design["leds"]["count"]
    n_ring = design["leds"].get("ring_count", n)
    S = [i * path.length / (n_ring - 1) for i in range(n_ring)]
    # SW2's NPTH locating pegs sit 0.25mm off the LED line and, against the
    # 45deg-rotated LED pads (0.81mm along-path reach), need the full 1.5mm
    # LED-bracketing clearance that the old 3.83mm grid gave for free; LED
    # courtyards (1.6mm squares, also at 45deg) need >=2.27mm LED-LED
    # spacing. At 2.44mm pitch both can't hold on an even grid, so the
    # chain is re-pitched around the switch: anchor LED4 stays at the
    # proven SW2 spot (S=7.75), LED3/LED5 sit exactly 3.0mm away (pegs at
    # LED4 +-1.5), LED2 splits the gap below, and the rest run evenly to
    # the path end (~2.40mm, still matching the tip group's ~2.45).
    if n_ring > 6 and path.length / (n_ring - 1) < 2.9:
        S[3] = 7.75
        S[2] = S[3] - 3.0
        S[1] = S[2] / 2
        S[4] = S[3] + 3.0
        rest = (path.length - S[4]) / (n_ring - 5)
        for i in range(5, n_ring):
            S[i] = S[4] + (i - 4) * rest
    pts = [path.point(si) for si in S]
    tangs = [path.tangent(si) for si in S]
    # tip closure (front): 3 LEDs continuing the chain from the right
    # straight across the tip, middle one higher (closer to the tip edge).
    # Coordinates clear the USB shell THT legs (±4.33, -14.88/-19.06) by
    # >2.1mm — the margin the existing path-end LEDs already prove out.
    TIP_PTS = [(2.45, -17.85), (0.0, -18.6), (-2.45, -17.85)]
    # interior ring around the CPU (chain continues from the tip): mirror-
    # symmetric octagon at r 9.2-9.7, threaded between the fixed ICs
    # (Y1/SW1 top, U3 left, U2 right, L1 bottom-left), inside the
    # perimeter bypass-cap band at r~11.35 and — critically — clear of the
    # locked USB pair's front-side crossing hop at (-4.34,-9.40)->
    # (-5.40,-8.75) + its vias (a locked-copper clearance violation makes
    # freerouting burn its whole budget; seen live with a top pair at
    # (+-5.0,-8.3)). Chain order: counterclockwise on screen from
    # top-left, so the hop from the tip chevron's last LED is shortest.
    INNER_PTS = [(-6.2, -6.8), (-9.3, -0.5), (-6.0, 7.6), (-2.2, 9.3),
                 (2.2, 9.3), (6.0, 7.6), (9.3, -0.5), (6.2, -6.8)]
    n_inner = design["leds"].get("inner_count", 0)
    if n > n_ring:
        assert n - n_ring == len(TIP_PTS) + n_inner, "chain group counts"
        assert n_inner in (0, len(INNER_PTS)), "inner ring is all-or-nothing"
        chain_tail = TIP_PTS + INNER_PTS[:n_inner]
        pts += chain_tail
        # tangents by finite difference along the extended chain
        # (duplicated last point -> one-sided difference at the chain end)
        ext = [pts[n_ring - 1]] + chain_tail + [chain_tail[-1]]
        for i in range(1, len(ext) - 1):
            dx = ext[i + 1][0] - ext[i - 1][0]
            dy = ext[i + 1][1] - ext[i - 1][1]
            L = math.hypot(dx, dy) or 1.0
            tangs.append((dx / L, dy / L))
    # pseudo polar angle matching the old circular convention
    pthetas = [math.degrees(math.atan2(t[1], t[0])) - 90 for t in tangs]

    best = None
    for k in range(4):
        for i in range(n):
            place(fps[f"LED{i+1}"], *pts[i], rot=(45.0 + 90.0 * k - pthetas[i]))
        total = 0.0
        for i in range(n - 1):
            a = pad_pos(fps[f"LED{i+1}"], LED_PIN["DO"])
            b = pad_pos(fps[f"LED{i+2}"], LED_PIN["DI"])
            total += math.hypot(a.x - b.x, a.y - b.y)
        if best is None or total < best[1]:
            best = (k, total)
    k = best[0]
    for i in range(n):
        place(fps[f"LED{i+1}"], *pts[i], rot=(45.0 + 90.0 * k - pthetas[i]))
    print(f"LED path: len={path.length:.1f}mm, orientation k={k}, "
          f"chain gap total {best[1]/1e6:.2f}mm")

    # bypass caps at every-2nd chain midpoint, shifted inward; slide along
    # the path if the spot lands on a USB shell THT leg or one of the two
    # NPTH locating pegs (tip straights)
    J1_LEGS = [(sx * 4.33, sy, 2.3) for sx in (-1, 1) for sy in (-14.88, -19.06)]
    J1_PEGS = [(sx * 2.90, -15.38, 1.6) for sx in (-1, 1)]
    for i in range(n_ring):
        ref = f"C{30+i}"
        if ref not in fps:
            continue
        sm = (S[i] + S[i + 1]) / 2 if i + 1 < n_ring else path.length - 1
        for slide in (0, 1.3, -1.3, 2.0, -2.0, 2.7, -2.7, 3.4, -3.4):
            smt = min(max(sm + slide, 0.5), path.length - 0.5)
            x, y = path.point(smt)
            nx, ny = path.normal_in(smt, design)
            px, py = x + nx * 1.9, y + ny * 1.9
            if all(math.hypot(px - lx, py - ly) > lr
                   for lx, ly, lr in J1_LEGS + J1_PEGS):
                break
        t = path.tangent(smt)
        rot = -(math.degrees(math.atan2(t[1], t[0])))
        place(fps[ref], px, py, rot=rot)
    # tip-closure bypass caps (i=n_ring, n_ring+2): inboard of the chevron,
    # between the D+/D- channel vias (y>=-15.0) and the tip LEDs' courtyards
    for ref, x in ((f"C{30 + n_ring}", 1.30), (f"C{30 + n_ring + 2}", -1.30)):
        if ref in fps:
            place(fps[ref], x, -16.30, rot=0)
    # interior-ring bypass caps (every 2nd inner LED gets one in circuit.py):
    # spread around the inner octagon, clear of the ICs and pre-placed vias
    for ref, (x, y, rot) in {
            # C68 moved off (-7.6,-0.6) to make room for the QSPI flash
            # U7 (RP2350A revision): now SW of LED39, rot 90. Pads at
            # r 8.6-8.9 — inboard of the r9.06-9.76 beautify annulus; its
            # courtyard corner pokes the annulus radially but arcs only
            # care about pads.
            f"C{30 + n_ring + 4}": (-8.35, -2.65, 90),
            f"C{30 + n_ring + 6}": (0.0, 8.55, 0),     # between LED41/LED42
            # (8.55 not 9.2: pads must stay off the r~9.4 annulus the
            # beautified chain arcs sweep between interior LEDs)
            f"C{30 + n_ring + 8}": (7.6, -0.6, 90),    # beside LED44
            # 4.06 (was 3.6): nudged east in the Aug 5 2026 crystal repack,
            # clearing the 3225's wider courtyard (Y1 cy right +1.925)
            f"C{30 + n_ring + 10}": (4.06, -6.9, 0),   # beside LED45
    }.items():
        if ref in fps:
            place(fps[ref], x, y, rot=rot)

    # ---------------- MCU + core cluster (front) ----------------
    place(fps["U1"], 0, -0.5, rot=180)  # USB pins (51/52) toward bottom
    # Crystal pocket — HAND-REPACKED Aug 5 2026 for the ABM8-272-T3 swap.
    # The RP2350-recommended crystal is a 3225, not the 2520 that used to
    # sit here: courtyard grew to +-1.925 x +-1.575, which broke the old
    # arrangement outright (the 2520's caps/R fouled the bigger pads).
    # These coordinates are MEASURED off Sequoia's routed board, not
    # re-derived. This is the tightest cluster on the front — every value
    # is load-bearing, and resolve_overlaps() below is a verified no-op
    # here (nothing collides), so they pass through unchanged.
    #
    # Y1 pushed north to -8.02 (was -6.7) to open room south of it; its
    # courtyard now spans y -9.595..-6.445. Rotation stays 180 so pad1
    # (XIN) lands at (+1.1,-8.87) and pad3 (XTAL_R) at (-1.1,-7.17) —
    # unrotated, XIN/XOUT arrive crossed and jam the crystal channel.
    place(fps["Y1"], 0, -8.02, rot=180)
    # C15 / R1 / C14 now sit in ONE ROW at y~-5.9, in the gap between the
    # crystal and U1 (QFN courtyard top -4.665). Both load caps face their
    # GND pad outboard and their signal pad inboard, keeping the crystal
    # loops short and pushing the returns out to the sides.
    # (C14's odd decimals are inherited from an earlier relaxation drift
    # and are kept verbatim so the generator reproduces the routed board.)
    place(fps["C15"], -2.74, -5.9, rot=180)    # XTAL_R load cap, west
    place(fps["R1"], -0.88, -5.9, rot=0)       # XOUT series R, centre
    place(fps["C14"], 1.2881, -5.9329, rot=0)  # XIN load cap, east
    # VREG cluster mirrors the official RPI-RP2350A-MINIMAL R4 layout
    # (rotated 180° to match U1): pins 46-50 sit at y=+2.94, x -2.8..-1.2.
    # CIN/COUT are CENTERED on the LX pin column at x=-2.00 exactly like the
    # official board — route.py transplants the official F.Cu pours (1V1,
    # LX, local GND, 3V3 finger) and the 0.3mm LX pour finger threads the
    # 0.56mm gap between the cap pad columns only at this x (at the old
    # -2.20 the hot pads pinch it below the 0.15 min fill width). Hot pads
    # land right/inboard, GND pads left into the local GND pour. L1 pad 1
    # (polarity dot) = VOUT side, per the official board. The AVDD RC
    # filter (R13/C22) columns to the left near pin 46. GND-return and
    # CFILT vias are pre-placed in route.py.
    # (y sits 0.04-0.15 lower than official: U1's courtyard extends 0.68
    # beyond its pad row and courtyard overlaps are DRC errors)
    place(fps["C11"], -2.00, 4.15, rot=180)  # CIN  (pad1 3V3 -> right)
    place(fps["C12"], -2.00, 5.20, rot=180)  # COUT (pad1 VDD_CORE -> right)
    place(fps["L1"], -2.00, 6.82, rot=180)   # pad2 LX left, pad1 dot right
    place(fps["R13"], -4.08, 6.30, rot=90)   # RFILT (pad1 3V3 far end)
    place(fps["C22"], -4.65, 4.37, rot=90)   # CFILT (pad1 AVDD far end)
    # 2nd VOUT cap near DVDD 23; low enough that the top-right pin row
    # keeps a >=0.5mm lateral escape channel above its courtyard
    place(fps["C13"], 3.9, -5.45, rot=0)
    # IOVDD decoupling: explicit pockets around the QFN courtyard (its
    # corners reach r≈6.2, so a uniform ring does not fit).
    # Left column: a rot-90 0402's pads span y +-0.83; the pad gaps are
    # SWDIO's crossing corridor (see the pitch note on DECAP below).
    # Right column: only THREE caps at 2.4 pitch — the IMU-signal +
    # LED_EN escapes need one gap each (single-lane pin corridor, see the
    # GPIO note in circuit.py), and a fourth cap walled off both chip
    # corners (the 10th decap is gone from circuit.py for the same
    # reason: no free real estate remained on the east side).
    # C1 down to -4.55 (was -4.3): 0.79mm pad gap to C3 = two 0.15 lanes
    # (SWDIO's crossing kept losing a single lane, chrg9 6/6). Keeps 0.22
    # to the committed CHRG via at (-4.6,-5.8). C5 only to 0.15: at 0.35
    # its pad came 0.041 from the committed CHRG_DONE via at (-4.6,1.35).
    # C7/C8 moved from (0,-9.3)/(-2.0,-9.6) to the band's east/west ends:
    # centered they filled the crystal->SW1 corridor wall-to-wall (chrg10
    # routed both stuck nets with it open). They now flank the 3225 crystal
    # (Y1 cy right +1.925, C7 cy left +2.245 -> 0.32 gap) and C8 is what the
    # re-scanned 3V3 pocket via at (-4.25,-7.55) in route.py feeds.
    # The old "do NOT flank SW1" warning STILL APPLIES, with new numbers:
    # SW1 is the SKRPAME010 at y=-11.2, and its pad copper reaches x
    # +-2.625 while its courtyard is only +-2.10 — so 0.53mm of copper
    # sticks out past the courtyard on each side (it was 1.3mm on the old
    # TS-1101). Anything placed on x 2.10..2.63 at y -12.62..-9.78 clears
    # the courtyard, survives relaxation, and shorts onto a switch pad.
    # The courtyard is deliberately NOT widened to cover the pads: at
    # +-2.75 x +-1.725 it would overlap Y1's courtyard (they sit 0.005mm
    # apart after the crystal repack) and trip courtyards_overlap.
    DECAP = [(-4.8, -4.55, 90), (4.8, -3.6, 90),
             (-4.8, -2.1, 90), (4.8, -1.2, 90),
             (-4.8, 0.15, 90), (4.8, 1.2, 90),
             (3.2, -8.8, 0), (-3.2, -8.8, 0), (-6.3, 5.7, 90)]
    for i, (x, y, rot) in enumerate(DECAP):
        place(fps[f"C{i+1}"], x, y, rot=rot)
    # RUN pullup, BOOTSEL series R, VBSENSE divider: moved to the BACK
    # (freeing the front interior for the inner LED ring) — see the
    # back-side block below.

    # ---------------- USB (back, at the teardrop tip) + charger ----------------
    og = geometry(design)
    overhang = design.get("usb", {}).get("overhang_mm", 1.3)
    j1_y = -og["tip_y"] + (5.21 - overhang)  # footprint +y extent = 5.21
    place(fps["J1"], 0, j1_y, rot=0, back=True)  # rot0: pads inboard, mouth out
    # USB series Rs: moved to the BACK, alongside the ESD chip and the
    # connector they serve, instead of the old front spot at (2.1, 4.75/5.90)
    # right of the VREG cluster. Measured off Sequoia's routed board.
    # The old front rationale ("R7/DM on top so the two locked escapes don't
    # cross on F.Cu") is dead with them on B.Cu — the escapes no longer
    # share a layer with the VREG cluster's front copper at all. The freed
    # front strip right of the VREG cluster is now unoccupied; if anything
    # is ever placed back there, keep the FB channel at x~-1.15 clear.
    place(fps["R7"], -2.56, -12.05, rot=180, back=True)  # DM series R
    place(fps["R6"], -2.56, -10.90, rot=180, back=True)  # DP series R
    # ESD chip on-axis right behind the connector (back top-center freed
    # by the hanger removal) — also clears the right-edge annulus band the
    # tip ring caps need for their VLED plane vias
    place(fps["U5"], 0, -11.5, rot=0, back=True)
    # CC pulldowns: pulled down-board from the tip strip — LED21/LED22 now
    # live on the tip straights behind the USB connector
    # (rot0 variants closer to the tip all clip locked copper or the NPTH
    # pegs — the checker caught R5.1 0.03 into the DP join at y=-15)
    place(fps["R4"], -2.0, -14.6, rot=90)
    place(fps["R5"], 2.0, -14.6, rot=90)
    place(fps["U2"], 5.5, 5.0, rot=0)
    # R8 (PROG) stays front near U2 (precision current-set node) but moves
    # up out of inner LED44's spot at (9.3,-0.5)
    place(fps["R8"], 8.6, 2.4, rot=90)
    place(fps["C16"], 8.3, 3.9, rot=90)
    place(fps["C17"], 7.9, 0.7, rot=90)
    # (charge LED D1 + series R9 removed: CHRG/DONE now route to GPIOs)

    # ---------------- power left/right (front) ----------------
    place(fps["U3"], -6.6, 3.4, rot=0)  # shifted left: clears CFILT (C22)
    place(fps["C18"], -8.5, 1.2, rot=90)
    place(fps["C19"], -8.3, 3.6, rot=90)
    place(fps["U4"], 6.6, -1.6, rot=0)
    place(fps["C20"], 6.3, -3.8, rot=90)  # tight to U4 output
    # R10 (LED_EN pulldown): moved to the BACK east pocket (below).
    # BOOTSEL series R stays FRONT: with R3 on the back, BOOTSEL's route
    # to it squatted USB_DP's loop lane below the bottom pin row (seen
    # live: deterministic DP residual). Pads at r<9.0 keep it out of the
    # LED44->LED45 beautify-arc band.
    place(fps["R3"], 7.7, -3.85, rot=90)

    # ---------------- power slide switch (back, left tip straight) ----------------
    # Body inboard, actuator knob (fp +y) overhanging the left straight edge
    # above the battery. Left edge runs corner(-4.7,-20.5)->tangency
    # (-12.70,-8.44); outward normal (-0.833,-0.553). The footprint's two
    # 0.9mm THT locating holes punch through — verify against front LEDs.
    # rot=56.4: the back-side flip NEGATES the rotation sense (scan-found).
    # Anchored to LED4: the two NPTH locating holes (3.0mm apart) only
    # clear the front LEDs by bracketing one LED at +-1.5mm, so the
    # hole-pair midpoint sits on LED4 — pinned at the proven S=7.75 spot by
    # the chain re-pitch above, which also holds LED3/LED5 exactly 3.0mm
    # away so the pegs keep their 1.5mm LED clearance at the denser pitch.
    # Center lands 2.30mm inboard: knob-side mounting pads
    # stay 0.25 inside the edge, interior courtyard face stays off the
    # cell disc (r 10.49 > 10.45), knob overhangs 1.23mm.
    nx_, ny_ = 0.833, 0.553             # inward normal of the left straight
    l4x, l4y = pts[3]                   # LED4 (path-derived, margin 2.0)
    place(fps["SW2"], l4x + 0.30 * nx_, l4y + 0.30 * ny_, rot=56.4, back=True)

    # ---------------- IMU (back, right tip straight, opposite SW2) ----------
    # Mirror of SW2's anchor across x=0; rot=-56.4 mirrors SW2's scan-found
    # orientation (the back-flip negates the rotation sense). Body center
    # sits 2.3mm inboard of the right straight edge: 1.05mm edge margin for
    # the 2.5mm-across LGA, inboard face at r~12 — outside the cell disc.
    ux_, uy_ = 0.553, 0.833             # along the right straight, downhill
    imu_x, imu_y = -(l4x + 0.30 * nx_), l4y + 0.30 * ny_
    place(fps["U6"], imu_x, imu_y, rot=-56.4, back=True)
    # VDD decap up-straight of the IMU, VDDIO decap radially inboard of it
    # (measured courtyards: IMU across-half 1.25, 0402 across-half 0.47 ->
    # 2.1mm center offset leaves 0.38 gap; C24 lands at r11.5, off the
    # cell disc)
    place(fps["C23"], imu_x + 2.2 * ux_, imu_y + 2.2 * uy_, rot=-56.4,
          back=True)
    place(fps["C24"], imu_x - 1.75, imu_y + 1.16, rot=-56.4, back=True)
    # Relocated passives, back east pocket, rot=90 single-file rows (0402
    # courtyards are 1.86x0.94 — rot90 packs 1.3mm x-pitch): clear of the
    # battery insertion sweep (y<0), the cell disc, U5, the locked USB
    # pair (x<=1.7 verticals), the IMU courtyard (x>=6.79) and the J1
    # shell legs (2.3mm THT keepout at (+-4.33,-14.88)).
    place(fps["R2"], 4.6, -11.3, rot=90, back=True)   # RUN pullup
    # SDA pull-up on row B, SCL pull-up on row A (not the reverse): the
    # row-A spot sits behind C24, and U6's SDA pad deterministically
    # failed to reach it; the row-B approach around the IMU's SW corner
    # is open
    place(fps["R15"], 5.9, -11.3, rot=90, back=True)  # IMU SCL pull-up
    # R10 at y -13.75 (was -13.35): opens the 0.42mm slot over its column
    # that IMU_INT1's proven route (In2 down x7.4, B entry from the
    # south) threads to reach U6.4 — at -13.35 the slot was 0.10mm.
    # R14 must STAY at -13.35: route.py puts a 3V3 via-in-pad in R14.2,
    # and at -13.75 that via lands 0.0mm from front LED33.1 (chrg10:
    # shorting_items + LED_D32 stranded).
    place(fps["R14"], 6.3, -13.35, rot=90, back=True) # IMU SDA pull-up
    place(fps["R10"], 7.6, -13.75, rot=90, back=True) # LED_EN pulldown
    # QSPI flash (RP2350A revision, no internal flash): FRONT, the pocket
    # west of the C3/C5 decap column that C68 used to occupy (C68 moved SW,
    # see the interior-bypass table). This was the ONLY legal spot found:
    # a full-front 0.1mm grid scan of the 2.24x3.86 pad envelope had zero
    # hits, the back is walled by BT1's 20.8mm cell-disc courtyard, and the
    # back tip band shorts J1's tie pads / violates the shell-leg keepouts.
    # Box: x -8.06..-6.06 (C18 east face .. C3/C5 column west face),
    # y -1.23..1.77 (drawn 2x3 courtyard); pad tips reach y -1.54/2.08 —
    # 0.03 from U3's courtyard EDGE but ~0.4 from its pads. QSPI wiring:
    # freerouting owns it (6-layer: In3 west run; 4-layer: B.Cu around the
    # locked USB rails' south end, y~7.3, then north along x~-6.2).
    # y 0.40 not 0.27: at 0.27 pad 5's tip sat 0.07mm from the C3/C5
    # column's 3V3 via at (-5.9,-1.2) (needs 0.127)
    place(fps["U7"], -7.06, 0.40, rot=0)
    place(fps["C25"], -6.75, -2.7, rot=90)   # flash VCC decap, below U7
    # VBSENSE divider: back lower-right shoulder, single-file (mirror band)
    place(fps["C21"], 12.3, 4.5, rot=90, back=True)
    place(fps["R11"], 11.65, 6.55, rot=90, back=True)
    place(fps["R12"], 11.55, 8.1, rot=0, back=True)

    # ---------------- back side ----------------
    # feet at ±x; rot=180 points the spring-finger mouth toward +y (the
    # round end / insertion corridor) — at rot=0 it faces the USB tip and
    # the cell would collide with the connector
    place(fps["BT1"], 0, 0, rot=180, back=True)
    # BOOTSEL: small top-actuated switch, front top-center — the spot the
    # hanger used to occupy. Also decongests the bottom-center routing zone
    # (VREG cluster + USB series Rs + 3V3 vias all live there now).
    # -11.2 (was -11.6), and the part is now the 4-pin SKRPAME010, whose
    # courtyard (+-2.10 x +-1.60) is smaller than the TS-1101 it replaced.
    # SW1 cy top -12.8 leaves 0.8 to R4/R5 (cy bottom -13.6), which cannot
    # move tipward — locked USB copper + NPTH pegs.
    # NOTE: the old "1.5mm-tall front highway" between the crystal and SW1
    # is GONE. The taller ABM8 crystal closed it to ~0.005mm (Y1 cy top
    # -9.595 vs SW1 cy bottom -9.6), so nothing routes up the centre any
    # more. IMU_INT1, which that corridor existed for, now runs east
    # instead (x 3.4..8.6). Do NOT re-derive a centre corridor from this
    # placement — if you need one back, SW1 and Y1 both have to move.
    place(fps["SW1"], 0, -11.2, rot=0)
    # testpoints: back shoulders, clear of the battery insertion corridor
    # (|x|<10.5, y>9.7) and the clip feet. TP3 sits on the lower-left
    # shoulder (flush pad: may overhang the cell insertion sweep).
    # TP3 (-11.55, 7.0), was (-12.15, 7.15): pulled inboard off the edge
    # during the Aug 5 2026 reroute. Measured off the routed board.
    for i, (x, y) in enumerate([(-11.8, -5.0), (11.8, -5.0), (-11.55, 7.0)]):
        place(fps[f"TP{i+1}"], x, y, back=True)

    resolve_overlaps(board, fps)
    pcbnew.SaveBoard(str(PCB), board)
    print(f"placed {len(fps)} footprints -> {PCB.name}")


def resolve_overlaps(board, fps, max_iter=300):
    """Relaxation pass: nudge small passives apart until no courtyard
    bboxes overlap. Ring caps (C30+) and non-passives stay fixed."""
    import re as _re

    # outer-wedge parts + the VREG reference-layout cluster stay exactly put
    EXEMPT = {"R4", "R5", "R8", "C11", "C12", "R13", "C22"}

    def movable(ref):
        if ref in EXEMPT:
            return False
        m = _re.match(r"([RC])(\d+)$", ref)
        if not m:
            return False
        return not (m.group(1) == "C" and int(m.group(2)) >= 30)

    def cy_poly(fp):
        cy_layer = (pcbnew.B_CrtYd if fp.GetLayer() == pcbnew.B_Cu
                    else pcbnew.F_CrtYd)
        fp.BuildCourtyardCaches()  # positions changed since load
        sh = fp.GetCourtyard(cy_layer)
        if sh.OutlineCount() == 0:
            sh = pcbnew.SHAPE_POLY_SET()
            bb = fp.GetBoundingBox(False)
            sh.NewOutline()
            for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                         (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())):
                sh.Append(x, y)
        return sh

    def collide(fa, fb):
        pa, pb = cy_poly(fa), cy_poly(fb)
        if not pa.BBox().Intersects(pb.BBox()):
            return False
        inter = pcbnew.SHAPE_POLY_SET(pa)
        inter.BooleanIntersection(pb)
        return inter.OutlineCount() > 0

    def cy_bbox(fp):
        return cy_poly(fp).BBox()

    for it in range(max_iter):
        moved = False
        items = list(fps.items())
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                ra, fa = items[i]
                rb, fb = items[j]
                if fa.GetLayer() != fb.GetLayer():
                    continue
                if not (movable(ra) or movable(rb)):
                    continue
                if not collide(fa, fb):
                    continue
                # push the movable one away from the other's center
                tgt, other = (fa, fb) if movable(ra) else (fb, fa)
                tp, op = tgt.GetPosition(), other.GetPosition()
                dx, dy = tp.x - op.x, tp.y - op.y
                norm = max(1, (dx * dx + dy * dy) ** 0.5)
                stepv = pcbnew.VECTOR2I(int(dx / norm * mm(0.15)),
                                        int(dy / norm * mm(0.15)))
                nx, ny = tp.x + stepv.x, tp.y + stepv.y
                rx, ry = nx - mm(CX), ny - mm(CY)
                rr = (rx * rx + ry * ry) ** 0.5
                if tgt.GetLayer() == pcbnew.B_Cu:
                    # back-side passives in the round region (y > -9.5) must
                    # stay OFF the cell disc + insertion sweep: r >= 11.0
                    lim = mm(11.0)
                    if ry > mm(-9.5) and rr < lim:
                        nx = mm(CX) + int(rx / rr * lim)
                        ny = mm(CY) + int(ry / rr * lim)
                else:
                    # front: clamp movable passives to the center cluster
                    # (r <= 9.3mm): beyond that lies the LED ring via band
                    lim = mm(9.3)
                    if rr > lim:
                        nx = mm(CX) + int(rx / rr * lim)
                        ny = mm(CY) + int(ry / rr * lim)
                tgt.SetPosition(pcbnew.VECTOR2I(int(nx), int(ny)))
                moved = True
        if not moved:
            if it:
                print(f"overlap relaxation converged after {it} iterations")
            break
    else:
        print("WARNING: overlap relaxation did not converge")
    # full-pair audit, fixed parts included: a courtyard overlap between
    # two non-movable parts (e.g. a mis-placed inner LED against an IC)
    # would otherwise surface only at DRC time
    items = list(fps.items())
    bad = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            (ra, fa), (rb, fb) = items[i], items[j]
            if fa.GetLayer() != fb.GetLayer():
                continue
            if collide(fa, fb):
                print(f"  COURTYARD OVERLAP: {ra} <-> {rb}")
                bad += 1
    if bad:
        print(f"WARNING: {bad} courtyard overlaps remain after relaxation")


if __name__ == "__main__":
    main()
