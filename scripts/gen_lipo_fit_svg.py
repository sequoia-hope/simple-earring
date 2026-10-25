#!/usr/bin/env python3
"""Generate out/lipo_fit.svg — where the LPR302823 LiPo sits on the back.

Why this diagram exists: the coin cell + clip (BT1) is being replaced by a
round LiPol LPR302823 pouch cell, taped to the back and wired to two solder
pads (design/intent.md). The cell is a Ø28 circle with one flat (the PCM end,
where the wires leave), and it has to clear the two tall things on the back
that it cannot sit on — J1 (USB-C, 3.2 mm) and SW2 (slide switch, 1.4 mm) —
across its FULL tolerance, not just nominal.

Geometry from design/datasheets/LPR302823.pdf (LiPol FD_6110_20):

    diameter      28 +-1.0
    flat-to-far   23 +-1.0       -> flat chord at d = L - R from the centre,
                                    7.5 .. 10.5 across the tolerance box
    thickness     3.0 (part name) / 3.2 (vendor page); the drawing's side
                  view prints "28 +-0.5", a drawing error. Designed to 3.2.

The tolerance envelope is the union over every legal (R, L) pair, plus
HAND_SLOP for hand placement. A point p is inside when
    |p| <= R_MAX + slop   and   p.n <= L_MAX - max(|p|, R_MIN) + slop
where n is the flat's outward normal.

The flat is square to the tip axis and the cell centre sits 0.25 mm away
from the tip. (A first draft rotated the flat 30 deg to dodge the old SW2
slide switch. Gate-4 review showed that was a knife edge against J1's real
copper; SW2 became a B3U side-push button further up the tip edge instead.)
HAND_SLOP is 0.3 rather than 0.5 because B.Silk alignment marks locate the
flat ends.

Views are TRUE BACK VIEWS: x is mirrored, so the page matches what you see
looking at the back of the board.

    python3 scripts/gen_lipo_fit_svg.py
"""
import math
import pathlib

import pcbnew
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

ROOT = pathlib.Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
OUT = ROOT / "out" / "lipo_fit.svg"

# --- the cell, from the datasheet -----------------------------------------
R_NOM, R_MIN, R_MAX = 14.0, 13.5, 14.5
L_NOM, L_MIN, L_MAX = 23.0, 22.0, 24.0
CELL_T = 3.2
FLAT_NORMAL_DEG = -90.0         # board coords (front view), -90 = toward tip
CELL_DY = 0.25                  # cell centre offset away from the tip
HAND_SLOP = 0.3

# --- the board side --------------------------------------------------------
# BT1's pads and the power button are read from the board (load_board)
UNDER_CELL_CAP = 1.1            # tallest part allowed under the cell
TAPE_T = 1.5                    # 3M VHB 4956: 0.4 over the cap, foam compresses
COIN_STACK = 3.8                # RJD2032C1 3.6 resting on the board in the
                                # MY-2032-12-R (3.70 model) — rev 2

# heights above the board, mm (datasheet max where known, else the 3D model).
# The SOT-323s are datasheet A max: CJ2101 0.900-1.100, Nexperia BAT54SW
# 0.8-1.1 (design/datasheets/). That 1.1 is what sets TAPE_T >= 1.2.
HEIGHT = {
    "R_0402_1005Metric": 0.40, "C_0402_1005Metric": 0.55,
    "LGA-14_L3.0-W2.5-P0.50-TL": 0.86, "SOT-323_MOSFET": 1.10,
    "SOT-323_BAT54SW": 1.10, "SW-TH_MSK12C02": 1.50, "SOT-666": 1.00,
    "SW_B3U-3000P": 1.35,       # Omron ds: 1.2 +0.15
    "TestPoint_Pad_1.5x1.5mm": 0.0,
    # one-button BOOTSEL + button ESD (2026-10-24)
    "SOT-363_SC-70-6": 1.10,    # Nexperia SOT363 A max (74LVC2G14 ds p.15)
    "D_SOD-323": 1.10,          # MDD 1N4007WS drawing 0.043in max; 1N4148WS same pkg
    "D_SOD-882": 0.50,          # Nexperia DFN1006-2 body 0.48
    "C_0603_1608Metric": 0.90,  # CL10A106KP8NNNC T = 0.8 +-0.1
    "YZV0004ADAD": 0.625,       # TPS22913 DSBGA max height (U9/U10, LED zones, 2026-10-24)
}

# --- dashboard palette (render.py write_index) ----------------------------
BG, CARD, LINE = "#1a1a1e", "#26262e", "#33333c"
FG, DIM = "#ddd", "#777"
GOOD, BAD, WARN = "#8f8", "#f88", "#fc6"
COPPER = "#c87137"
SCALE = 13.0                    # px per mm in the plan view
ESCALE = 22.0                   # px per mm in the elevation


def cell_poly(R, L, slop=0.0):
    """One cell outline (front-view board coords), flat toward FLAT_NORMAL."""
    d = L - R
    disc = Point(0, 0).buffer(R + slop, 256)
    half = box(-60, -(d + slop), 60, 60)              # normal = -y
    half = affinity.rotate(half, FLAT_NORMAL_DEG + 90, origin=(0, 0))
    return affinity.translate(disc.intersection(half), 0, CELL_DY)


def envelope():
    """Union of every legal (R, L) outline, plus hand-placement slop."""
    polys = []
    for i in range(11):
        R = R_MIN + (R_MAX - R_MIN) * i / 10
        polys.append(cell_poly(R, L_MAX, HAND_SLOP))
    return unary_union(polys)


def load_board():
    b = pcbnew.LoadBoard(str(PCB))
    mm = pcbnew.ToMM
    ol = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(ol)
    o = ol.Outline(0)
    outline = [(mm(o.CPoint(i).x) - 100, mm(o.CPoint(i).y) - 100)
               for i in range(o.PointCount())]
    parts, pads = [], []
    for p in b.FindFootprintByReference("BT1").Pads():
        ps = pcbnew.SHAPE_POLY_SET()
        p.TransformShapeToPolygon(ps, pcbnew.B_Cu, 0, pcbnew.FromMM(0.005),
                                  pcbnew.ERROR_INSIDE)
        c = ps.Outline(0)
        pads.append((p.GetNumber(), "+" if p.GetNetname() == "VBATT" else "-",
                     Polygon([(mm(c.CPoint(j).x) - 100, mm(c.CPoint(j).y) - 100)
                              for j in range(c.PointCount())])))
    for f in b.GetFootprints():
        if f.GetLayer() != pcbnew.B_Cu or f.GetReference() == "BT1":
            continue
        cy = f.GetCourtyard(pcbnew.B_CrtYd)
        polys = []
        for i in range(cy.OutlineCount()):
            c = cy.Outline(i)
            polys.append(Polygon([(mm(c.CPoint(j).x) - 100,
                                   mm(c.CPoint(j).y) - 100)
                                  for j in range(c.PointCount())]))
        # plus the real pad copper: J1's courtyard does NOT cover its SMT
        # row or shell legs (gate-4 and gate-6 reviews both caught a
        # courtyard-only clearance claim)
        for pd in f.Pads():
            if not pd.IsOnLayer(pcbnew.B_Cu):
                continue
            ps = pcbnew.SHAPE_POLY_SET()
            pd.TransformShapeToPolygon(ps, pcbnew.B_Cu, 0,
                                       pcbnew.FromMM(0.005), pcbnew.ERROR_INSIDE)
            for i in range(ps.OutlineCount()):
                c = ps.Outline(i)
                polys.append(Polygon([(mm(c.CPoint(j).x) - 100,
                                       mm(c.CPoint(j).y) - 100)
                                      for j in range(c.PointCount())]))
        fpname = str(f.GetFPID().GetLibItemName())
        parts.append(dict(ref=f.GetReference(), poly=unary_union(polys),
                          h=HEIGHT.get(fpname)))
    return outline, parts, pads


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Panel:
    def __init__(self, cx, cy):
        self.cx, self.cy, self.o = cx, cy, []

    def px(self, dx, dy):
        return self.cx - dx * SCALE, self.cy + dy * SCALE   # mirror x

    def shape(self, g, **kw):
        attrs = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kw.items())
        for p in getattr(g, "geoms", [g]):
            if p.is_empty:
                continue
            pts = " ".join(f"{x:.1f},{y:.1f}"
                           for x, y in (self.px(*q) for q in p.exterior.coords))
            self.o.append(f'<polygon points="{pts}" {attrs}/>')

    def label(self, dx, dy, text, fill=FG, size=10, anchor="middle", weight=400):
        x, y = self.px(dx, dy)
        self.o.append(f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" '
                      f'font-size="{size}" text-anchor="{anchor}" '
                      f'font-weight="{weight}">{esc(text)}</text>')


def build():
    outline, parts, pads = load_board()
    env = envelope()
    nom = cell_poly(R_NOM, L_NOM)

    def colour(p):
        if p["ref"] == "J1" or (p["h"] or 0) > UNDER_CELL_CAP:
            return BAD
        if (p["h"] or 0) > 0.6:
            return WARN
        return "#4a4a55"

    clash = [p["ref"] for p in parts
             if (p["ref"] == "J1" or (p["h"] or 0) > UNDER_CELL_CAP)
             and p["poly"].intersects(env)]
    under = sorted(p["ref"] for p in parts if p["poly"].intersects(env))

    W, H = 1180, 820
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="ui-sans-serif,system-ui,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{BG}"/>']

    P = Panel(330, 400)
    P.shape(Polygon(outline), fill=CARD, stroke=FG, stroke_width="1.5")
    P.shape(env, fill=BAD, fill_opacity=".10", stroke=BAD, stroke_width="1",
            stroke_dasharray="4 3")
    for p in parts:
        P.shape(p["poly"], fill=colour(p), fill_opacity=".75", stroke="#000",
                stroke_width=".5")
        c = p["poly"].centroid
        if p["poly"].area > 3:
            P.label(c.x, c.y + 0.3, p["ref"], "#fff", 8.5)
    P.shape(nom, fill=GOOD, fill_opacity=".10", stroke=GOOD, stroke_width="2")
    for num, sign, poly in pads:
        P.shape(poly, fill=COPPER, stroke="#fff", stroke_width=".8")
        c = poly.centroid
        P.label(c.x, c.y + 0.45, sign, "#000", 13, weight=700)
    # flat midpoint -> wire exit
    n = (math.cos(math.radians(FLAT_NORMAL_DEG)),
         math.sin(math.radians(FLAT_NORMAL_DEG)))
    d = L_NOM - R_NOM
    P.label(n[0] * (d - 1.6), n[1] * (d - 1.6) + CELL_DY, "PCM / wires", GOOD, 10)
    P.label(0, 3.0, "LPR302823", GOOD, 15, weight=600)
    P.label(0, 4.6, "Ø28 · 140 mAh · 3.2 mm", DIM, 10)
    o.append("\n".join(P.o))

    # legend
    lx, ly = 690, 120
    rows = [(GOOD, "cell, nominal (flat 9.0 from centre, square to the tip, "
                   f"centre +{CELL_DY} away)"),
            (BAD, f"worst-case envelope: Ø28±1, 23±1, + {HAND_SLOP} hand placement"),
            ("#4a4a55", "up to 0.6 mm part (0402, test pad)"),
            (WARN, f"0.6–{UNDER_CELL_CAP} mm part, fine under {TAPE_T} mm tape"),
            (BAD, f"over {UNDER_CELL_CAP} mm: must stay outside (J1, SW2 button)"),
            (COPPER, "BT1 wire pads 1.0×1.5, one each side of J1")]
    for i, (col, txt) in enumerate(rows):
        y = ly + i * 24
        o.append(f'<rect x="{lx}" y="{y-11}" width="16" height="14" rx="2" '
                 f'fill="{col}" fill-opacity=".8"/>')
        o.append(f'<text x="{lx+26}" y="{y}" fill="{FG}" font-size="12">'
                 f'{esc(txt)}</text>')
    ok = not clash
    o.append(f'<text x="{lx}" y="{ly+170}" fill="{GOOD if ok else BAD}" '
             f'font-size="14" font-weight="600">'
             f'{"J1 and SW2 clear across the whole envelope" if ok else "CLASH: " + ", ".join(clash)}'
             f'</text>')
    for k, chunk in enumerate((under[:10], under[10:])):
        lead = f"under the cell ({len(under)}): " if k == 0 else ""
        o.append(f'<text x="{lx}" y="{ly+192+k*17}" fill="{DIM}" '
                 f'font-size="11">{lead}{esc(", ".join(chunk))}</text>')
    o.append(f'<text x="{lx}" y="{ly+232}" fill="{DIM}" font-size="11">'
             f'TP1–TP3 (RUN/SWD) are reachable only before the cell goes on</text>')
    sw = next(p for p in parts if p["ref"] == "SW2")["poly"]
    o.append(f'<text x="{lx}" y="{ly+252}" fill="{DIM}" font-size="11">'
             f'SW2 (B3U) / J1 copper+courtyard to the envelope: '
             f'{sw.distance(env):.2f} / '
             f'{next(p for p in parts if p["ref"] == "J1")["poly"].distance(env):.2f} mm</text>')

    # elevation
    ey = 690
    o.append(f'<text x="{lx}" y="{ey-210}" fill="{FG}" font-size="15" '
             f'font-weight="600">Z height above the back copper</text>')

    def stack(x0, label, layers, col):
        bw, y = 170, ey
        o.append(f'<rect x="{x0}" y="{ey}" width="{bw}" height="8" '
                 f'fill="#4a7" fill-opacity=".55"/>')
        for h, name, c in layers:
            hh = h * ESCALE
            y -= hh
            o.append(f'<rect x="{x0+15}" y="{y:.1f}" width="{bw-30}" '
                     f'height="{hh:.1f}" rx="2" fill="{c}" fill-opacity=".6"/>')
            o.append(f'<text x="{x0+bw/2}" y="{y+hh/2+4:.1f}" fill="#fff" '
                     f'font-size="10" text-anchor="middle">{esc(name)}</text>')
        tot = sum(h for h, _, _ in layers)
        o.append(f'<text x="{x0+bw/2}" y="{y-8:.1f}" fill="{col}" '
                 f'font-size="14" font-weight="600" text-anchor="middle">'
                 f'{tot:.1f} mm</text>')
        o.append(f'<text x="{x0+bw/2}" y="{ey+26}" fill="{FG}" font-size="11" '
                 f'text-anchor="middle">{esc(label)}</text>')

    stack(lx, "rev 2: RJD2032C1 in clip · 85 mAh",
          [(3.6, "cell 3.6", DIM), (COIN_STACK - 3.6, "", COPPER)], WARN)
    stack(lx + 220, "LiPo: LPR302823 · ~120 mAh at 4.2 V",
          [(TAPE_T, f"foam tape {TAPE_T}", "#5577aa"),
           (CELL_T, f"cell {CELL_T}", GOOD)], GOOD)
    o.append(f'<text x="{W/2}" y="{H-14}" fill="{DIM}" font-size="10.5" '
             f'text-anchor="middle">back of the board, true back view (x '
             f'mirrored), to scale · read live from out/earring.kicad_pcb · '
             f'scripts/gen_lipo_fit_svg.py</text>')
    o.append("</svg>")
    OUT.write_text("\n".join(o))
    print(f"wrote {OUT}")
    print(f"  clash: {clash or 'none'}")
    sw = next(p for p in parts if p["ref"] == "SW2")["poly"]
    j1 = next(p for p in parts if p["ref"] == "J1")["poly"]
    print(f"  SW2 to envelope {sw.distance(env):.2f}  J1 to envelope {j1.distance(env):.2f}")
    print(f"  under the cell: {', '.join(under)}")


if __name__ == "__main__":
    build()
