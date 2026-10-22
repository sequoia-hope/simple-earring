#!/usr/bin/env python3
"""Generate custom footprints into library/parts.pretty.

1. LED_TBA-C1010MB — NationStar TBA-C1010MB-J2I16 (LCSC C22461778)
   From datasheet (rev A, 2022-12): 1.0x1.0mm body, recommended land:
   0.4x0.4mm pads, 0.3mm gaps both axes -> pad centers at (±0.35, ±0.35).
   We use 0.45mm pads for solderability (0.25mm pad-to-pad gap remains).
   Pin table: 1=DI (top-left), 2=VCC (bottom-left), 3=GND (top-right),
   4=DO (bottom-right) — positions per the see-through (x-ray) top view.

2. BAT_CR2032_W — QIJEY CR2032-W SMD retainer clip (LCSC C70373)
   Drawing: 26.3mm total span, feet 1.75mm long at each end, cell dia 20.3mm.
   Pads: two 3.0x4.5mm feet pads (both pin 1, battery +, the clip grips the
   cell's positive can sides) and an 8mm exposed-copper center pad (pin 2,
   battery − face). Datasheet's optional through-holes omitted: front side
   carries the LED ring, so no through-holes allowed under the clip feet.
   RETIRED Aug 2026: the drawing's holes are NOT optional — the feet are
   bent (弯脚) for through-hole reverse-side soldering; on a hole-less board
   the clip rides on its foot tips and won't clamp the cell. Kept only
   because the ordered rev (43eadc1) was fabbed with this footprint.

3. BAT_MY2032_12R — MYOUNG MY-2032-12-R SMD retainer clip (LCSC C964834)
   Flat-foot replacement for the QIJEY: no holes needed, so it coexists
   with the front-side LED ring. Drawing MY-CP-0120: 24.1mm tip-to-tip,
   body 15.22mm wide (wings stay inside the 20mm cell shadow — feet are
   the only board contact), 3.6mm tall. Datasheet land: 2.4x6.1mm pads at
   ±11.35 (foot metal spans 10.65..12.05). Copper here is kept IDENTICAL
   to BAT_CR2032_W (3.0x4.5 pads at ±12.4, spanning 10.9..13.9) so the
   routed/ordered layout is unchanged: 1.15mm of each foot lands on-pad.
   Rev-2 TODO: widen pads inward to ~10.15 to match the datasheet land.

   NEGATIVE CONTACT (rev 2, 2026-08-31). The first assembled board would not
   hold the cell against the centre pad: 176 B.Cu track endpoints sit within
   r9.5 of it, and 35um of copper under 20um of soldermask stands ~25um
   PROUD of a bare pad face, so the rigid coin rode on mask and never
   touched copper. The bench fix that worked was hand-tinning the pad.
   Baking that in is NOT just "add paste to the Ø8 pad": molten solder on
   one big bare opening has nothing to hold it, so it wets the whole 8mm
   and levels out ~8um thick. Solder only stands proud if soldermask dams
   it. So the centre contact is now a RING OF SIX MASK-DEFINED BUMPS —
   Ø1.2 openings on r2.8, each pasted 1:1 — over the same Ø8 copper, which
   is itself left mask-covered. At a 0.12mm stencil each aperture holds
   ~0.07mm3 of solder, which domes ~0.12mm above the pad, i.e. ~65um clear
   of the mask plane everywhere else under the coin. Six on a ring, not one
   in the middle: three points define the plane the coin sits on, and a
   single central dome would let it rock. The Ø8 copper stays exactly as
   it was, so nothing the router already solved moves.
   The alternative fix — a B.Cu keepout under the coin — needs r8 to clear
   the whole negative face, i.e. a Ø16 hole in the back-side routing on a
   30.5mm board. Not affordable here; revisit if the back ever empties out.

4. BAT_LPR302823_PADS — two solder pads for the LiPol LPR302823 round LiPo
   (replaces BAT_MY2032_12R, 2026-10-22). Not assembled; the cell's wires are
   hand-soldered and the cell is taped to the back. Pads are pasted so JLC
   leaves them pre-tinned for that.
   The footprint origin is the board centre and it is placed on the BACK at
   rot 180 (see place.py), so its local x is the mirror of board x: pad 1
   (+, VBATT) lands at board (+6.0, -16.0) on the IMU side of J1, pad 2 (-,
   GND) at (-5.6, -16.7) on the power-button side, >=0.6mm from all other
   copper (sweep in design/gates/phase6.md).
   The cell outline (Ø28, flat 9.0 from centre, square to the tip, centre
   0.25 away from the tip) is drawn on Fab. It is NOT a courtyard, because
   parts up to 1.1mm legitimately sit under the cell.

5. SW_B3U-3000P — Omron B3U-3000P side-actuated tact switch (LCSC C963349),
   the LiPo board's power button (replaces the MSK12C02 slide switch).
   From design/datasheets/B3U-3000P.pdf p.3 ("Side-actuated, without ground
   terminal, without boss"): body 3.0 x 2.5, height 1.2 +0.15/-0.10,
   actuator 0.7 past the body face (3.2 total depth), terminals span 4.0.
   PCB pad (top view): 4.2 outer, 2.6 inner -> two 0.8 x 1.7 pads at x=+-1.7,
   centred on the body's depth. No holes, no boss. Origin = body centre,
   actuator toward local -y. The courtyard deliberately stops at the body
   face on the actuator side: the actuator overhangs the board edge.
"""
import math
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "library" / "parts.pretty"


def pad_smd(num, x, y, w, h, shape="rect", paste=True, roundrect=0.25):
    layers = '"F.Cu" "F.Mask"' + (' "F.Paste"' if paste else "")
    rr = f"\n    (roundrect_rratio {roundrect})" if shape == "roundrect" else ""
    return (
        f'  (pad "{num}" smd {shape} (at {x} {y}) (size {w} {h})'
        f" (layers {layers}){rr})"
    )


def led_tba_c1010():
    p = 0.35  # pad center offset
    s = 0.45  # pad size
    pads = [
        pad_smd(1, -p, -p, s, s),  # DI  top-left
        pad_smd(3, p, -p, s, s),   # GND top-right
        pad_smd(2, -p, p, s, s),   # VCC bottom-left
        pad_smd(4, p, p, s, s),    # DO  bottom-right
    ]
    body = 0.5
    lines = []
    # courtyard
    c = 0.8
    lines.append(
        f"  (fp_rect (start {-c} {-c}) (end {c} {c})"
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))'
    )
    # fab outline
    lines.append(
        f"  (fp_rect (start {-body} {-body}) (end {body} {body})"
        ' (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))'
    )
    # pin-1 (DI) marker: silk dot outside top-left corner
    lines.append(
        '  (fp_circle (center -0.85 -0.85) (end -0.78 -0.85)'
        ' (stroke (width 0.12) (type default)) (fill solid) (layer "F.SilkS"))'
    )
    texts = [
        '  (fp_text reference "REF**" (at 0 -1.4) (layer "F.SilkS") hide'
        " (effects (font (size 0.4 0.4) (thickness 0.08))))",
        '  (fp_text value "TBA-C1010MB-J2I16" (at 0 1.4) (layer "F.Fab") hide'
        " (effects (font (size 0.4 0.4) (thickness 0.08))))",
    ]
    # back-ported hand edit: regenerating used to drop the 3D model outright
    model = ['  (model "${KIPRJMOD}/../library/3d/ee.3dshapes/LED_TBA-C1010MB.wrl"',
             "    (offset (xyz 0 0 0))",
             "    (scale (xyz 1 1 1))",
             "    (rotate (xyz 0 0 0))",
             "  )"]
    content = "\n".join(
        [
            '(footprint "LED_TBA-C1010MB"',
            "  (version 20240108) (generator gen_footprints)",
            '  (layer "F.Cu")',
            '  (descr "NationStar TBA-C1010MB-J2I16 1010 RGB LED, LCSC C22461778, land per datasheet")',
            '  (tags "LED RGB addressable 1010")',
            "  (attr smd)",
        ]
        + texts
        + lines
        + pads
        + model
        + [")"]
    )
    (LIB / "LED_TBA-C1010MB.kicad_mod").write_text(content)
    print("wrote LED_TBA-C1010MB.kicad_mod")


def bat_cr2032_w():
    foot_x = 12.4  # pad centers; feet solder zone 11.4..13.15mm
    lines = []
    # cell outline on silk (20.3mm circle) + polarity marks
    lines.append(
        "  (fp_circle (center 0 0) (end 10.15 0)"
        ' (stroke (width 0.15) (type default)) (fill none) (layer "F.SilkS"))'
    )
    # courtyard: three disjoint shapes (feet tabs + cell circle) — a rect
    # overlapping the circle would be a self-intersecting courtyard.
    lines.append(
        "  (fp_rect (start -14.1 -3.4) (end -10.5 3.4)"
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))'
    )
    lines.append(
        "  (fp_rect (start 10.5 -3.4) (end 14.1 3.4)"
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))'
    )
    lines.append(
        "  (fp_circle (center 0 0) (end 10.4 0)"
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))'
    )
    lines.append(
        '  (fp_text user "+" (at 0 -11.5) (layer "F.SilkS")'
        " (effects (font (size 1 1) (thickness 0.2))))"
    )
    pads = [
        pad_smd(1, -foot_x, 0, 3.0, 4.5),
        pad_smd(1, foot_x, 0, 3.0, 4.5),
        # center contact: bare copper, no paste
        '  (pad "2" smd circle (at 0 0) (size 8 8) (layers "F.Cu" "F.Mask"))',
    ]
    # rotate 180: back-ported hand edit — the vendor wrl faces the wrong way
    # in the render. Regenerating used to silently drop this (see the module
    # docstring's drift note); it lives here now so a rerun is idempotent.
    model = ['  (model "${KIPRJMOD}/../library/3d/ee.3dshapes/BAT-SMD_CR2032_C70373.wrl"',
             "    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 180)))"]
    texts = [
        '  (fp_text reference "REF**" (at 0 -13.2) (layer "F.SilkS")'
        " (effects (font (size 1 1) (thickness 0.15))))",
        '  (fp_text value "CR2032-W" (at 0 13.2) (layer "F.Fab")'
        " (effects (font (size 1 1) (thickness 0.15))))",
    ]
    content = "\n".join(
        [
            '(footprint "BAT_CR2032_W"',
            "  (version 20240108) (generator gen_footprints)",
            '  (layer "F.Cu")',
            '  (descr "QIJEY CR2032-W SMD coin cell retainer clip, LCSC C70373. Clip=+ (pin1), center pad=- (pin2). Cell + marking faces out.")',
            '  (tags "battery RJD2032C1 CR2032 retainer")',
            "  (attr smd)",
        ]
        + texts
        + lines
        + pads
        + model
        + [")"]
    )
    (LIB / "BAT_CR2032_W.kicad_mod").write_text(content)
    print("wrote BAT_CR2032_W.kicad_mod")


def bat_my2032_12r():
    foot_x = 12.4  # SAME copper as BAT_CR2032_W — see module docstring
    lines = []
    # cell outline on silk (20.3mm circle) + polarity marks
    lines.append(
        "  (fp_circle (center 0 0) (end 10.15 0)"
        ' (stroke (width 0.15) (type default)) (fill none) (layer "F.SilkS"))'
    )
    # courtyard: disjoint feet rects + cell circle (see BAT_CR2032_W note).
    # Feet rects trimmed to the shorter body: tips at ±12.05, pads to 13.9.
    lines.append(
        "  (fp_rect (start -14.1 -3.4) (end -10.5 3.4)"
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))'
    )
    lines.append(
        "  (fp_rect (start 10.5 -3.4) (end 14.1 3.4)"
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))'
    )
    lines.append(
        "  (fp_circle (center 0 0) (end 10.4 0)"
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))'
    )
    lines.append(
        '  (fp_text user "+" (at 0 -11.5) (layer "F.SilkS")'
        " (effects (font (size 1 1) (thickness 0.2))))"
    )
    # negative contact: the Ø8 copper is left UNDER mask now, carrying six
    # mask-defined, pasted bumps — see the module docstring for why bare
    # copper (and bare copper plus paste) both fail here.
    bump_r, bump_d = 2.8, 1.2
    bumps = []
    for i in range(6):
        a = math.radians(60 * i)
        bx, by = round(bump_r * math.cos(a), 3), round(bump_r * math.sin(a), 3)
        bumps.append(
            f'  (pad "2" smd circle (at {bx} {by}) (size {bump_d} {bump_d})'
            ' (layers "F.Cu" "F.Mask" "F.Paste"))'
        )
    pads = [
        pad_smd(1, -foot_x, 0, 3.0, 4.5),
        pad_smd(1, foot_x, 0, 3.0, 4.5),
        '  (pad "2" smd circle (at 0 0) (size 8 8) (layers "F.Cu"))',
    ] + bumps
    model = ['  (model "${KIPRJMOD}/../library/3d/ee.3dshapes/BAT-SMD_MY-2032-12_C964834.wrl"',
             "    (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))"]
    texts = [
        '  (fp_text reference "REF**" (at 0 -13.2) (layer "F.SilkS")'
        " (effects (font (size 1 1) (thickness 0.15))))",
        '  (fp_text value "MY-2032-12-R" (at 0 13.2) (layer "F.Fab")'
        " (effects (font (size 1 1) (thickness 0.15))))",
    ]
    content = "\n".join(
        [
            '(footprint "BAT_MY2032_12R"',
            "  (version 20240108) (generator gen_footprints)",
            '  (layer "F.Cu")',
            '  (descr "MYOUNG MY-2032-12-R SMD coin cell retainer clip, LCSC C964834. Clip=+ (pin1), center pad=- (pin2). Flat feet, no thru-holes. Copper identical to BAT_CR2032_W (ordered rev).")',
            '  (tags "battery RJD2032C1 CR2032 retainer")',
            "  (attr smd)",
        ]
        + texts
        + lines
        + pads
        + model
        + [")"]
    )
    (LIB / "BAT_MY2032_12R.kicad_mod").write_text(content)
    print("wrote BAT_MY2032_12R.kicad_mod")


def bat_lpr302823_pads():
    pad_w, pad_h = 1.2, 1.6
    # LOCAL (mirrored) coords + local rotation. Board: pad 1 (+) at
    # (+6.0,-16.0), pad 2 (-) at (-5.6,-16.7), each tipped to follow its
    # tip straight. Swept against ALL B.Cu copper (pads, locked tracks and
    # vias) at >=0.6mm; the tip LEDs' VLED vias are then placed AFTER this
    # and kept >=0.6mm off these pads by route.py (gate-6 review: an
    # earlier sweep ran before those vias existed and they landed 0.27mm
    # from the pads — a solder slip would have put the cell on VLED).
    # Rotation: the sweep is in shapely (counter-clockwise in y-up maths,
    # i.e. CLOCKWISE on this y-down board), KiCad's angles run the other
    # way, and place() flips + turns the footprint 180. Net effect board =
    # 180 - local, so local 150/30 land as board 30/150 — the orientations
    # the sweep actually cleared. (A first pass used the sweep's numbers
    # directly and put pad 1 0.34mm from J1's shell leg.)
    pads_xy = [(1, -6.0, -16.0, 150), (2, 5.6, -16.7, 30)]
    lines = []
    for _, x, y, r in pads_xy:
        # courtyard = the pad rectangle + 0.15, rotated with it (a circle
        # around the pad's diagonal crossed J1's courtyard)
        a, hw, hh = math.radians(-r), pad_w / 2 + 0.15, pad_h / 2 + 0.15
        cs = [(x + u * math.cos(a) - v * math.sin(a),
               y + u * math.sin(a) + v * math.cos(a))
              for u, v in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]
        pts = " ".join(f"(xy {cx:.3f} {cy:.3f})" for cx, cy in cs)
        lines.append(f"  (fp_poly (pts {pts})"
                     ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))')
    # nominal cell outline on Fab: Ø28 with the flat 9.0 from centre, flat
    # square to the tip, centre 0.25 away from the tip (design/brief.md)
    r, d, nrm, dy = 14.0, 9.0, math.radians(-90.0), 0.25
    half = math.acos(d / r)              # half-angle the flat subtends
    a0, a1 = nrm + half, nrm - half + 2 * math.pi
    pts = [(r * math.cos(a0 + (a1 - a0) * i / 96),
            r * math.sin(a0 + (a1 - a0) * i / 96) + dy) for i in range(97)]
    xy = " ".join(f"(xy {x:.3f} {y:.3f})" for x, y in pts)
    lines.append(f"  (fp_poly (pts {xy})"
                 ' (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))')
    texts = [
        '  (fp_text reference "REF**" (at 0 0) (layer "F.Fab")'
        " (effects (font (size 1 1) (thickness 0.15))))",
        '  (fp_text value "LPR302823" (at 0 2) (layer "F.Fab")'
        " (effects (font (size 1 1) (thickness 0.15))))",
        '  (fp_text user "+" (at -6.0 -14.6) (layer "F.Fab")'
        " (effects (font (size 0.8 0.8) (thickness 0.12))))",
        '  (fp_text user "-" (at 5.6 -15.3) (layer "F.Fab")'
        " (effects (font (size 0.8 0.8) (thickness 0.12))))",
    ]
    pads = [pad_smd(n, x, y, pad_w, pad_h, shape="roundrect")
            .replace(f"(at {x} {y})", f"(at {x} {y} {r})")
            for n, x, y, r in pads_xy]
    content = "\n".join(
        [
            '(footprint "BAT_LPR302823_PADS"',
            "  (version 20240108) (generator gen_footprints)",
            '  (layer "F.Cu")',
            '  (descr "Wire pads for the LiPol LPR302823 round LiPo (hand-fitted, not assembled). Pad 1 = + (VBATT), pad 2 = - (GND). Origin = board centre; place on the back at rot 0. Fab outline = nominal cell, flat square to the tip.")',
            '  (tags "battery LiPo LPR302823 wire pads")',
            "  (attr smd exclude_from_pos_files exclude_from_bom)",
        ]
        + texts
        + lines
        + pads
        + [")"]
    )
    (LIB / "BAT_LPR302823_PADS.kicad_mod").write_text(content)
    print("wrote BAT_LPR302823_PADS.kicad_mod")


def sw_b3u_3000p():
    lines = [
        # body + actuator on Fab
        "  (fp_rect (start -1.5 -1.25) (end 1.5 1.25)"
        ' (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))',
        "  (fp_rect (start -0.85 -1.95) (end 0.85 -1.25)"
        ' (stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))',
        # courtyard: pads + body, flush with the body face on the actuator side
        "  (fp_rect (start -2.35 -1.25) (end 2.35 1.5)"
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))',
    ]
    texts = [
        '  (fp_text reference "REF**" (at 0 0) (layer "F.Fab")'
        " (effects (font (size 0.6 0.6) (thickness 0.1))))",
        '  (fp_text value "B3U-3000P" (at 0 0.8) (layer "F.Fab")'
        " (effects (font (size 0.4 0.4) (thickness 0.06))))",
    ]
    pads = [pad_smd(1, 1.7, 0, 0.8, 1.7), pad_smd(2, -1.7, 0, 0.8, 1.7)]
    content = "\n".join(
        ['(footprint "SW_B3U-3000P"',
         "  (version 20240108) (generator gen_footprints)",
         '  (layer "F.Cu")',
         '  (descr "Omron B3U-3000P side-actuated tact switch, LCSC C963349. Actuator toward -y, overhangs the board edge. Pads per Omron PCB pad drawing (4.2/2.6 span, 1.7 tall).")',
         '  (tags "switch tactile side B3U")',
         "  (attr smd)"]
        + texts + lines + pads + [")"]
    )
    (LIB / "SW_B3U-3000P.kicad_mod").write_text(content)
    print("wrote SW_B3U-3000P.kicad_mod")


def hanger_loop(hole=1.5, pad=2.7):
    """Plated ear-wire loop hole; annular copper both sides for strength."""
    content = "\n".join([
        '(footprint "HANGER_LOOP"',
        "  (version 20240108) (generator gen_footprints)",
        '  (layer "F.Cu")',
        '  (descr "Ear-wire loop: plated hole, no net, not assembled")',
        '  (tags "mechanical hanger")',
        "  (attr through_hole exclude_from_pos_files exclude_from_bom)",
        '  (fp_text reference "REF**" (at 0 -2.2) (layer "F.SilkS") hide'
        " (effects (font (size 0.5 0.5) (thickness 0.08))))",
        '  (fp_text value "HANGER" (at 0 2.2) (layer "F.Fab") hide'
        " (effects (font (size 0.5 0.5) (thickness 0.08))))",
        f'  (fp_circle (center 0 0) (end {pad / 2 + 0.25} 0)'
        ' (stroke (width 0.05) (type default)) (fill none) (layer "F.CrtYd"))',
        f'  (pad "1" thru_hole circle (at 0 0) (size {pad} {pad})'
        f' (drill {hole}) (layers "*.Cu" "*.Mask"))',
        ")",
    ])
    (LIB / "HANGER_LOOP.kicad_mod").write_text(content)
    print("wrote HANGER_LOOP.kicad_mod")


if __name__ == "__main__":
    led_tba_c1010()
    bat_cr2032_w()
    bat_my2032_12r()
    bat_lpr302823_pads()
    sw_b3u_3000p()
    hanger_loop()
