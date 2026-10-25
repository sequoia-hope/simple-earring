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
from circuit import LED_PIN, build_circuit, led_zones, load_design  # noqa: E402
from outline import led_path, geometry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
CX, CY = 100.0, 100.0
# SW2 (B3U-3000P) rotation on the back: actuator (footprint -y) must point
# along the left straight's outward normal (-0.833,-0.553). Measured off the
# placed footprint, since the back-side flip negates the rotation sense.
SW2_ROT = -123.6
# soft power latch spots (see the latch block in main); "park" = off-board,
# not yet scanned
LATCH = {
    "Q5": (-5.75, -4.00, 0),
    "D4": (-6.25, -6.50, 0), "Q4": (-8.50, -3.50, 0),
    "R24": (-7.75, -1.75, 0), "R25": (-5.75, -2.25, 0),
    "C27": (-6.75, -8.50, 0),      # BTN_N debounce, behind R30 (D6 took its old spot)
}


# Locked for the user's autorouter (2026-10-24); everything else may be
# nudged. User's list: every LED*, J1 (USB), SW2 (button). Added because
# they are physically constrained: BT1 (cell wire pads vs the cell envelope).
# Added because locked copper or a fixed pour lands on their pads, so a
# nudge would orphan it: U1 (VDD_CORE FB link, ring stubs, VREG pours),
# U5 (VBUS via-in-pad + trunk),
# R14 (3V3 via-in-pad), and the RP2350 reference VREG cluster L1 / C11 /
# C12 / C13 / R13 / C22 (copied from the official minimal board). (U2 was
# locked for its CHRG / CHRG_DONE pre-routes until it moved to the back on
# 2026-10-25; those pre-routes are gone.)
LOCKED = {"J1", "SW2", "BT1", "U1", "U5", "R14",
          "L1", "C11", "C12", "C13", "R13", "C22",
          "Q1"}  # ALS-PT19: optical/aesthetic spot by the heart (review C8)
# LED zone drivers (2026-10-24): (x, y, rot, back), filled in by scan_spot;
# None = parked off-board until scanned.
ZONES = {
    "U9": (6.75, -1.50, 0, True),
    "R33": (7.75, -1.00, 90, True),
    "C78": (5.75, 0.25, 0, True),
    "U10": (-5.75, 2.50, 0, True),
    "R34": (-6.00, 1.50, 0, True),
    "C79": (-6.25, 3.75, 0, True),
    "Q9": (-9.25, -9.75, 0, True),
    "R31": (-9.50, -8.00, 0, True),
    "Q10": (-9.00, -6.25, 0, True),
    "R32": (-11.00, -7.25, 90, True),
}
# Moved from the front to the back (2026-10-25) to free the area around
# U1. All of it is <= 1.1 mm (gen_lipo_fit_svg.py HEIGHT, datasheet max),
# so legal under the cell. (x, y, rot); None = parked off-board until
# scanned. Spots from tools/scan_spot.py in signal order, pads kept out of
# the U1 back keepout (+-5.6 x -6..5) for its escape vias, r <= 10.5 at the
# bottom to stay off the URL silk arc, then nudged clear of other back silk
# (scan_spot can still miss a courtyard touch: re-run DRC after any move):
#   U7 flash just south of the QSPI pin row. At rot 180 its north row
#     carries SCLK/SD0/SD3 (+VCC), a via and ~3 mm each; SD1/SD2//CS are
#     on the far row and wrap round the body (~6 mm). R3 beside /CS so
#     the QSPI_SS stub stays short (BOOTSEL_SW, the slow side, runs to
#     Q7); C25 at pin 8.
#   East: charger U2 with C17 (VBATT) between it and Q2's drain, C16 (VBUS)
#     at pin 4, R8 at PROG; D3, R22/R21, C29 and the R19/R20 tap on the
#     same VBUS run. VBUS_SENSE (DC level, 5k) runs west to pin 41.
#   West: U4 (LED_L) by the outer-band VLED_L half it feeds, C20 on A1,
#     R10 north of C20; LED_EN_L (slow GPIO) crosses from pin 3. LDO U3
#     with EN facing R17/D2, C18 on VSYS between U3.6 and U4.A2, C19 at
#     the 3V3 pin.
# Q3/R23 stay on the front: no back spot near the LED_DATA_L -> LED1 line.
BACK = {
    "U7": (1.50, 7.00, 180), "C25": (3.25, 5.70, 270),
    "U2": (5.25, 7.25, 270), "C16": (6.62, 4.62, 0), "C17": (7.25, 6.88, 90), "R8": (3.45, 7.60, 270),
    "U3": (-5.88, 6.50, 180), "C18": (-7.80, 5.85, 270), "C19": (-3.95, 6.25, 270),
    "D3": (9.07, 4.82, 90), "C29": (9.60, 1.45, 0), "R22": (9.00, 2.70, 180), "R21": (7.57, 2.95, 90),
    "R19": (7.00, 1.50, 0), "R20": (9.20, 0.20, 0),
    "U4": (-8.80, 5.07, 0), "C20": (-9.30, 3.82, 0), "R10": (-8.80, 2.60, 180), "R3": (2.20, 9.85, 0),
}
# one-button BOOTSEL + button ESD (2026-10-24): (x, y, rot, back). Every
# spot came out of tools/scan_spot.py in signal order, with the previously
# placed ones on the board and a centre keepout of +-5.6 x (-6.0..5.0)
# around U1 so its pin-escape vias keep the back directly under the chip.
# The button's D6/R30 sit where the crowded tip first had room (4.4mm from
# SW2.2): the routed order must stay SW2.2 -> D6.1 -> R30 -> BTN_N, so the
# clamp is ahead of everything it protects. U8 sits east, between R2 (RUN)
# and R3's old front spot; Q7 sat directly under R3 (R3 moved beside U7's
# /CS on 2026-10-25, so BOOTSEL_SW is now a back trace); Q6/R29 took SW1's
# old front spot (0, -11.2), clear of the silk art, the only place left
# with room for a SOT-323 near RUN.
ONEBTN = {
    "D6": (-6.00, -11.75, 270, True),  # TVS on the SW2.2 -> R30 line (C27's old spot)
    "R30": (-5.50, -10.00, 180, True), # pad 1 (BTN_EXT) east, 2 (BTN_N) west
    "R26": (-2.75, -8.50, 0, True),    # PRESS_N pull-up, under Q8's gate
    "Q8": (-3.50, -6.75, 0, True),     # drain faces D4/R27
    "R27": (-4.75, -8.50, 180, True),  # BTN_SENSE pad east, at Q8.3
    "R28": (-1.00, -6.25, 0, True),
    "C75": (0.75, -6.75, 90, True),    # BOOT_TMR pad north, toward U8.1
    "D5": (0.75, -9.25, 0, True),
    "U8": (3.50, -7.00, 0, True),
    "C77": (6.00, -7.00, 90, True),    # beside U8.5 (VCC)
    "Q7": (7.25, -4.75, 0, True),      # drain BOOTSEL_SW -> R3 (beside U7 /CS)
    "C76": (4.50, -9.25, 90, True),    # beside U8.4 (LONG); RUN_KICK vias to Q6 on the front
    "R29": (-3.25, -12.75, 90, False), # beside Q6's gate
    "Q6": (-1.00, -11.00, 180, False),  # front, SW1's old spot; drain RUN
}


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
    if back != (fp.GetLayer() == pcbnew.B_Cu):  # re-runs: a parked back part may land front
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

    # Orientation per ZONE (2026-10-24): each zone is its own chain, and the
    # right zone runs against the path direction (LED37 -> LED19), so each
    # picks the quarter-turn k that puts every DO nearest the next DI.
    ks, gap_total = {}, 0.0
    for z, chain in led_zones(design).items():
        best = None
        for k in range(4):
            for i in chain:
                place(fps[f"LED{i}"], *pts[i - 1], rot=(45.0 + 90.0 * k - pthetas[i - 1]))
            total = 0.0
            for a_i, b_i in zip(chain, chain[1:]):
                a = pad_pos(fps[f"LED{a_i}"], LED_PIN["DO"])
                b = pad_pos(fps[f"LED{b_i}"], LED_PIN["DI"])
                total += math.hypot(a.x - b.x, a.y - b.y)
            if best is None or total < best[1]:
                best = (k, total)
        ks[z] = best[0]
        gap_total += best[1]
        for i in chain:
            place(fps[f"LED{i}"], *pts[i - 1], rot=(45.0 + 90.0 * best[0] - pthetas[i - 1]))
    print(f"LED path: len={path.length:.1f}mm, orientation k={ks}, "
          f"chain gap total {gap_total/1e6:.2f}mm")

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
    # C28 (USBLC6 local VBUS 100n): was never placed — since its Aug 6
    # datasheet-review add it fell through to the relaxer, which shoved
    # it from the board-center seed to (0,4.2) FRONT, squatting the
    # south-center B->F transition corridor and stretching a VBUS branch
    # 10mm into the interior. The ST note that motivated it (USBLC6 ds
    # §3: 100n right at the part) wants it HERE, beside U5 on the back.
    # Scanned spot (see D2's note); the relaxer may nudge it off U5's
    # courtyard sliver — that's fine, it's movable.
    place(fps["C28"], 2.0, -11.3, rot=90, back=True)
    # CC pulldowns: pulled down-board from the tip strip — LED21/LED22 now
    # live on the tip straights behind the USB connector
    # (rot0 variants closer to the tip all clip locked copper or the NPTH
    # pegs — the checker caught R5.1 0.03 into the DP join at y=-15)
    place(fps["R4"], -2.0, -14.6, rot=90)
    place(fps["R5"], 2.0, -14.6, rot=90)
    # (charger U2 + R8/C16/C17: back, see BACK)
    # (charge LED D1 + series R9 removed: CHRG/DONE now route to GPIOs)

    # ---------------- power left/right (front) ----------------
    # (LDO U3 + C18/C19, LED_L switch U4 + C20, R3: back, see BACK. R17,
    # the PWR_EN pulldown, lives on the back next to D2.)

    # ---------------- power button (back, left tip straight) ----------------
    # LiPo change: the MSK12C02 slide switch is gone (the Ø28 cell covers
    # its spot at every legal angle) and SW2 is now an Omron B3U-3000P
    # side-push tact on the same straight, further toward the tip so its
    # body clears the cell's worst-case envelope. Spot from a sweep along
    # the edge against the envelope (+0.3 placement slop, centre 0.25 off
    # the tip) and J1's real pad copper: body face on the edge line, body
    # centre 1.25 inboard, 0.67mm best clearance (design/gates/phase4.md).
    # The B3U has no holes, but the LED chain re-pitch above (built around
    # the slide switch's NPTH pegs) is KEPT so the ring, its locked arcs
    # and the IMU's mirrored anchor below stay exactly where they were.
    nx_, ny_ = 0.833, 0.553             # inward normal of the left straight
    l4x, l4y = pts[3]                   # LED4 (anchors the IMU mirror below)
    place(fps["SW2"], -7.71, -13.70, rot=SW2_ROT, back=True)
    # ---- soft power latch (Q4/Q5/D4/R24/R25), back, under the cell ----
    # All <=1.1mm (SOT-323 A max 1.1, 0402s), so legal under the LiPo.
    # Clustered west of the MCU's pin-32/33 escape corridor (x > -5.6 kept
    # clear so those pins can via down), between the button (BTN_N, up
    # the left tip) and D2 (SW_ON, lower-left shoulder). Each spot comes
    # from tools/scan_spot.py run in signal order against the board with
    # the previous ones placed (pad polygons, locked pre-routes, holes).
    for ref, (x, y, r) in LATCH.items():
        place(fps[ref], x, y, rot=r, back=True)
    # D2 (BAT54SW EN diode-OR, rev 2) + R17 (PWR_EN pulldown): back
    # LOWER-LEFT shoulder, between TP3 and the insertion corridor.
    # Spots from a full-board grid scan against the STATIC board (all
    # courtyards + all PAD copper at 0.25 mask margin + route.py's
    # locked vias/tracks + holes + edge + the insertion corridor).
    # Courtyards alone are NOT enough here: SW2's pin pads stick out
    # past its courtyard polygon (same trap as SW1) — a first placement
    # in SW2's pocket put D2.3 shorting_items-close to SW2.3, and under
    # the pad-aware model that pocket has NO legal SC-70 spot (nor does
    # anywhere else for a SOT-23, which is why the part is SC-70).
    # The shoulder is also the better topology: SW_ON runs SW2 -> D2.1
    # -> R11 (right shoulder) as one arc along the open back annulus,
    # VBATT is the clip's west foot 6mm north, and PWR_EN heads up the
    # west corridor to U3 — the same channel the old SW2->U3 PWR_EN
    # route proved out. D refs are NOT relaxer-movable: keep exact.
    place(fps["D2"], -9.1, 8.2, rot=90, back=True)
    place(fps["R17"], -7.4, 8.7, rot=90, back=True)
    # R18 (VBUS -> PWR_EN 100k): back tip, the pocket WEST of J1's GND
    # tie pad — the VBUS leg hops to the locked A4B9 via-in-pad at
    # (-2.35,-13.45), PWR_EN heads down the west corridor to D2/U3.
    # BEWARE placing anything else near the tip ties: J1's A1B12/A4B9
    # are CUSTOM pads that report GetSize 0.01x0.01 — their real copper
    # spans x -3.60..-2.05, y -14.82..-13.42 (GetEffectivePolygon), so
    # size-based scans sail right through them. Two earlier spots
    # ((-1.0,-13.1) and (-3.4,-13.1)) DRC'd as shorting/mask-bridging
    # against the ties, J1's pin field and the locked USB_C_DN via.
    # This one is hand-verified against the real polygons: 0.39 to
    # C30's VLED via-in-pad, 0.33 to R7.2, 0.2 to SW2's mount pad
    # face, 1.16 to J1's shell-leg pad copper.
    place(fps["R18"], -4.45, -12.4, rot=0, back=True)

    # ---------------- IMU (back, right tip straight, opposite SW2) ----------
    # Mirror of SW2's anchor across x=0; rot=-56.4 mirrors SW2's scan-found
    # orientation (the back-flip negates the rotation sense). Body center
    # sits 2.3mm inboard of the right straight edge: 1.05mm edge margin for
    # the 2.5mm-across LGA, inboard face at r~12 — outside the cell disc.
    ux_, uy_ = 0.553, 0.833             # along the right straight, downhill
    imu_x, imu_y = -(l4x + 0.30 * nx_), l4y + 0.30 * ny_
    place(fps["U6"], imu_x, imu_y, rot=-56.0, back=True)
    # VDD decap up-straight of the IMU, VDDIO decap radially inboard of it
    # (measured courtyards: IMU across-half 1.25, 0402 across-half 0.47 ->
    # 2.1mm center offset leaves 0.38 gap; C24 lands at r11.5, off the
    # cell disc)
    # C23/C24: coordinates back-ported from the ORDERED board (43eadc1)
    # rather than the old formula+relaxer spots — the formula landed C23
    # 0.3mm off and, with the rot drift below, 0.15mm-violating U6's NC
    # pads. Rotations are 56.0, not 56.4: the ordered board (DRC 0/0)
    # was built with 56.0; the committed 56.4 was never what shipped.
    place(fps["C23"], 10.054, -8.274, rot=-56.0, back=True)
    place(fps["C24"], 6.767, -8.946, rot=124.0, back=True)
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
    # (R10 and the QSPI flash U7 + C25: back, see BACK)
    # VBSENSE divider: back lower-right shoulder, single-file (mirror band)
    place(fps["C21"], 12.3, 4.5, rot=90, back=True)
    place(fps["R11"], 11.65, 6.55, rot=90, back=True)
    place(fps["R12"], 11.55, 8.1, rot=0, back=True)

    # Ambient light sensor (rev 2): FRONT — must see the world when worn.
    # Spot from a courtyard grid-scan (scan excluded the heart silk box
    # x -0.9..3.0 / y 5.2..8.0, the upper text arcs y<0 & r>9.5, and
    # r>13): SE interior beside the heart, r7.5, 2.8mm from the nearest
    # octagon LEDs (42/41). R16 east of Q1 (load, near the E pad), C26
    # north above the heart corner toward the pin-40 escape.
    place(fps["Q1"], 3.25, 6.75, rot=90)
    place(fps["R16"], 4.5, 7.6, rot=90)   # load, east of the E pad
    place(fps["C26"], 2.0, 8.1, rot=0)    # filter, below the heart tip
    # (C26's spot is where overlap relaxation settled it from a seed at
    # (2.2,9.05); hardcoded so placement stays deterministic)

    # ---------------- back side ----------------
    # BT1 = the LPR302823 LiPo's two wire pads (the coin clip that lived
    # here until 4538da2 is gone). The footprint's origin is the board
    # centre and its pad offsets are pre-mirrored in x for the back. rot
    # 180, not 0: place()'s flip mirrors y and the 180 turns that into the
    # x-mirror the footprint assumes (same reason the clip sat at 180).
    # Pad 1 (+) lands at (+5.7,-16.9) on the IMU side of J1, pad 2 (-) at
    # (-5.7,-16.9) on the power-button side.
    # The comments below that cite "BT1's cell-disc courtyard" or "the clip
    # feet" describe why rev-2 parts sit where they do. The constraint is
    # gone, but the placement was kept as-is on purpose (brief §7).
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
    # (SW1 removed 2026-10-24: the power button's long hold does BOOTSEL.
    # Its front top-centre spot is free again.)
    # testpoints: back shoulders, clear of the battery insertion corridor
    # (|x|<10.5, y>9.7) and the clip feet. TP3 sits on the lower-left
    # shoulder (flush pad: may overhang the cell insertion sweep).
    # TP3 (-11.55, 7.0), was (-12.15, 7.15): pulled inboard off the edge
    # during the Aug 5 2026 reroute. Measured off the routed board.
    for i, (x, y) in enumerate([(-11.8, -5.0), (11.8, -5.0), (-11.55, 7.0)]):
        place(fps[f"TP{i+1}"], x, y, back=True)

    # ---------------- rev-2 power path + LED level shifter ----------------
    # All spots below come from tools/scan_spot.py, which models real pad
    # polygons (not courtyards, and not GetSize — see the D2/R18 notes and
    # the pcbnew-gotchas memory) against courtyards, tracks, vias, drills
    # and the edge.
    #
    # Q2 is a SOT-323, and a full front sweep at 0.2mm clearance found the
    # front has exactly SIX legal SC-70 spots on the whole board — all of
    # them in the south-west, nowhere near the charger. So the ORing FET
    # lives on the back annulus instead, on the south-east shoulder: the
    # mirror of D2/R17's proven band (same radius, r12.2), outside BT1's
    # r10.4 cell disc and inboard of the R11/R12/C21 divider.
    # rot 90 puts the gate at (8.60,7.20) — a via up to R22 directly above
    # — and the source (VSYS) at (9.90,7.20), facing the open east flank
    # the VSYS run uses. The drain (VBATT) then points south, away from the
    # +x clip foot, which is the one compromise: VBATT reaches it either
    # around the annulus or through a via to C17 on the front, and at 40mA
    # neither run costs anything measurable.
    place(fps["Q2"], 9.25, 8.00, rot=90, back=True)
    # (R22, R21, D3, C29 and the R19/R20 VBUS tap: back, see BACK)
    # Q3 (LED data level shifter) takes the best of those six SC-70 front
    # spots — and it happens to sit almost exactly on the line from the
    # MCU's LED_DATA pin (-2.40,-3.94) to LED1's DI pad (-4.36,-17.40),
    # 6.8mm from one and 6.9mm from the other. Gate lands at (-3.45,-9.85)
    # facing the MCU, drain at (-5.05,-10.50) facing the ring. rot 0 is the
    # only legal orientation here.
    place(fps["Q3"], -4.25, -10.50, rot=0)

    # R23 pulls LEDL_D0 up to VLED_L, 1.8mm off Q3's drain. (Since the zone
    # split it sits over the VLED_C band, so its VLED_L feed is a trace out
    # to the outer band, r > 11.15.)
    place(fps["R23"], -5.25, -8.75, rot=0)


    # ---- LED zone drivers (2026-10-24), see ZONES ----
    for i, (ref, spot) in enumerate(ZONES.items()):
        if spot is None:
            place(fps[ref], 30 + 5 * (i % 5), -10 + 5 * (i // 5), back=True)
        else:
            place(fps[ref], *spot[:3], back=spot[3])
    # ---- one-button BOOTSEL + button ESD (2026-10-24), see ONEBTN ----
    for ref, (x, y, r, back) in ONEBTN.items():
        place(fps[ref], x, y, rot=r, back=back)

    # ---- front -> back move (2026-10-25), see BACK ----
    for i, (ref, spot) in enumerate(BACK.items()):
        if spot is None:
            place(fps[ref], 30 + 4 * (i % 6), 15 + 4 * (i // 6), back=True)
        else:
            place(fps[ref], *spot, back=True)

    resolve_overlaps(board, fps)
    # see LOCKED at the top for why each part is locked
    for ref, fp in fps.items():
        fp.SetLocked(ref.startswith("LED") or ref in LOCKED)
    pcbnew.SaveBoard(str(PCB), board)
    print(f"placed {len(fps)} footprints -> {PCB.name}")


def resolve_overlaps(board, fps, max_iter=300):
    """Relaxation pass: nudge small passives apart until no courtyard
    bboxes overlap. Ring caps (C30+) and non-passives stay fixed."""
    import re as _re

    # outer-wedge parts + the VREG reference-layout cluster stay exactly put.
    # The rev-2 power-path/shifter passives and the VBUS tap join them: every
    # one of those spots came out of tools/scan_spot.py against the static
    # board, and a relaxer nudge silently invalidates that (R20's scanned
    # spot was legal until relaxation slid it 0.8mm into R16).
    EXEMPT = {"R4", "R5", "R8", "C11", "C12", "R13", "C22",
              "R19", "R20", "R21", "R22", "R23", "C29"} | set(ONEBTN) | set(ZONES) | set(BACK)

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
