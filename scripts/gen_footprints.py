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
"""
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
            '  (tags "battery LIR2032 CR2032 retainer")',
            "  (attr smd)",
        ]
        + texts
        + lines
        + pads
        + [")"]
    )
    (LIB / "BAT_CR2032_W.kicad_mod").write_text(content)
    print("wrote BAT_CR2032_W.kicad_mod")


if __name__ == "__main__":
    led_tba_c1010()
    bat_cr2032_w()
