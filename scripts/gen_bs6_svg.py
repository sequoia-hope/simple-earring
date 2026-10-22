#!/usr/bin/env python3
"""Generate out/bs6_fit.svg — the C22363833 (CR2032-BS-6) fit test.

Why this diagram exists: the MY-2032-12-R retainer needs the cell's negative
face to touch a bare Ø8 pad in the middle of the back, which is why the centre
contact is a ring of six mask-defined solder bumps (gen_footprints.py). A
socket-style holder carries its own negative contact and would retire that
whole hack — so C22363833 was evaluated as a replacement.

Geometry from the LCSC datasheet for C22363833 (深圳市连欣科技 CR2032-6
镀金电池座SMT). READ THE OUTLINE CAREFULLY — the part is not its bounding box:

    plastic body   16.0 wide x 28.8 long, corners chamfered C1.5
    metal tabs     7.1 wide, reaching out to +-15.95 (this is the 31.9 overall)
    cell pocket    dia 20.2, open at the sides (the coin is proud of the body)
    height         5.5 +-0.1 above the PCB, foot standoff 0.15
    land           two pads 1.9 x 5.0, centres 30.6 apart (= +-15.30)

Drawing the 31.9 x 16.0 bounding rectangle as if it were the body overstates
the plastic overhang by ~5x (2.50mm vs the true 0.55mm) — the ends that reach
31.9 are narrow metal tabs, not full-width plastic.

Board outline, back-side placement and BT1's real pads are read out of
out/earring.kicad_pcb. Panel 3 is the best placement found by sweeping position
x rotation for one where BOTH lands sit fully on board: they exist (2227 of
them), but every one puts the holder body on top of J1.

Views are TRUE BACK VIEWS: x is mirrored, so the page matches what you see
looking at the back of the board.

    python3 scripts/gen_bs6_svg.py
"""
import math
import pathlib

import pcbnew

ROOT = pathlib.Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"
OUT = ROOT / "out" / "bs6_fit.svg"

# --- candidate, from the datasheet ----------------------------------------
BS6_BODY_L, BS6_BODY_W, BS6_CH = 28.8, 16.0, 1.5
BS6_TAB_OUT, BS6_TAB_W = 15.95, 7.1
BS6_POCKET_D = 20.2
BS6_PAD_PITCH, BS6_PAD_W, BS6_PAD_H = 30.6, 1.9, 5.0
BS6_H = 5.5
MY_H = 3.6                      # MY-2032-12-R, drawing MY-CP-0120
MY_SPAN, MY_BODY_W = 24.1, 15.22
CELL_T = 3.6                    # RJD2032C1

# best land-legal placement, from the position x rotation sweep
ALT_X, ALT_Y, ALT_ROT = 1.75, -2.50, 72

R_BOARD = 15.25

# --- dashboard palette (render.py write_index) ----------------------------
BG, CARD, LINE = "#1a1a1e", "#26262e", "#33333c"
FG, DIM = "#ddd", "#777"
GOOD, BAD, WARN = "#8f8", "#f88", "#fc6"
COPPER = "#c87137"

SCALE = 8.3                     # px per mm in the plan views
ESCALE = 15.0                   # px per mm in the elevation


def body_poly():
    """True plastic outline: 28.8 x 16.0 with C1.5 corners, centred, +x long."""
    hl, hw, c = BS6_BODY_L / 2, BS6_BODY_W / 2, BS6_CH
    return [(hl, hw - c), (hl - c, hw), (-(hl - c), hw), (-hl, hw - c),
            (-hl, -(hw - c)), (-(hl - c), -hw), (hl - c, -hw), (hl, -(hw - c))]


def tab_polys():
    hl, tw = BS6_BODY_L / 2, BS6_TAB_W / 2
    return [[(hl, tw), (BS6_TAB_OUT, tw), (BS6_TAB_OUT, -tw), (hl, -tw)],
            [(-hl, tw), (-BS6_TAB_OUT, tw), (-BS6_TAB_OUT, -tw), (-hl, -tw)]]


def rot(pts, deg, dx=0.0, dy=0.0):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return [(x * ca - y * sa + dx, x * sa + y * ca + dy) for x, y in pts]


def load_board():
    b = pcbnew.LoadBoard(str(PCB))
    mm = lambda v: v / 1e6
    parts = []
    for f in b.GetFootprints():
        if f.GetLayer() != pcbnew.B_Cu:
            continue
        bb = f.GetBoundingBox()
        parts.append(dict(
            ref=f.GetReference(), val=f.GetValue(),
            x0=mm(bb.GetLeft()) - 100, x1=mm(bb.GetRight()) - 100,
            y0=mm(bb.GetTop()) - 100, y1=mm(bb.GetBottom()) - 100))
    bt1 = b.FindFootprintByReference("BT1")
    pads = []
    for p in bt1.Pads():
        pos, sz = p.GetPosition(), p.GetSize()
        pads.append(dict(num=p.GetNumber(), x=mm(pos.x) - 100, y=mm(pos.y) - 100,
                         w=mm(sz.x), h=mm(sz.y),
                         circle=p.GetShape() == pcbnew.PAD_SHAPE_CIRCLE))
    return parts, pads


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Panel:
    """A plan view of the back of the board, centred at (cx, cy) in px."""

    def __init__(self, cx, cy):
        self.cx, self.cy, self.o = cx, cy, []

    def px(self, dx, dy):
        return self.cx - dx * SCALE, self.cy + dy * SCALE   # mirror x

    def outline(self):
        pts = [self.px(*p) for p in
               [(-12.71, -8.43), (-4.70, -20.50), (4.70, -20.50), (12.71, -8.43)]]
        r = R_BOARD * SCALE
        d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        d += f" A {r:.1f},{r:.1f} 0 1 0 {pts[0][0]:.1f},{pts[0][1]:.1f} Z"
        self.o.append(f'<path d="{d}" fill="{CARD}" stroke="{FG}" '
                      f'stroke-width="1.5"/>')
        return self

    def parts(self, parts, hot=()):
        for p in parts:
            if p["ref"] == "BT1":
                continue
            xa, ya = self.px(p["x0"], p["y0"])
            xb, yb = self.px(p["x1"], p["y1"])
            x, y, w, h = min(xa, xb), min(ya, yb), abs(xb - xa), abs(yb - ya)
            is_hot = p["ref"] in hot
            self.o.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
                f'height="{h:.1f}" rx="1" fill="{BAD if is_hot else "#4a4a55"}" '
                f'fill-opacity="{".85" if is_hot else ".5"}"/>')
            if is_hot and w * h > 46:
                self.o.append(
                    f'<text x="{x+w/2:.1f}" y="{y+h/2+3:.1f}" fill="#fff" '
                    f'font-size="7.5" text-anchor="middle">{esc(p["ref"])}</text>')
        return self

    def poly(self, pts, **kw):
        d = " ".join(f"{x:.1f},{y:.1f}" for x, y in (self.px(*p) for p in pts))
        attrs = " ".join(f'{k.replace("_","-")}="{v}"' for k, v in kw.items())
        self.o.append(f'<polygon points="{d}" {attrs}/>')
        return self

    def circle(self, dx, dy, dia, **kw):
        x, y = self.px(dx, dy)
        attrs = " ".join(f'{k.replace("_","-")}="{v}"' for k, v in kw.items())
        self.o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" '
                      f'r="{dia/2*SCALE:.1f}" {attrs}/>')
        return self

    def rectp(self, cx, cy, w, h, deg=0, **kw):
        pts = rot([(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2),
                   (-w / 2, h / 2)], deg, cx, cy)
        return self.poly(pts, **kw)

    def label(self, dx, dy, text, fill=FG, size=10, anchor="middle", weight=400):
        x, y = self.px(dx, dy)
        self.o.append(f'<text x="{x:.1f}" y="{y:.1f}" fill="{fill}" '
                      f'font-size="{size}" text-anchor="{anchor}" '
                      f'font-weight="{weight}">{esc(text)}</text>')
        return self

    def svg(self):
        return "\n".join(self.o)


def draw_bs6(P, dx=0.0, dy=0.0, deg=0.0, pad_col=WARN):
    """the candidate, drawn as its real outline rather than a bounding box"""
    P.poly(rot(body_poly(), deg, dx, dy), fill=BAD, fill_opacity=".17",
           stroke=BAD, stroke_width="1.5")
    for t in tab_polys():
        P.poly(rot(t, deg, dx, dy), fill=DIM, fill_opacity=".55",
               stroke=DIM, stroke_width=".8")
    cx, cy = rot([(0, 0)], deg, dx, dy)[0]
    P.circle(cx, cy, BS6_POCKET_D, fill="none", stroke=BAD, stroke_width="1",
             stroke_dasharray="4 3", stroke_opacity=".6")
    for s in (+1, -1):
        px, py = rot([(s * BS6_PAD_PITCH / 2, 0)], deg, dx, dy)[0]
        P.rectp(px, py, BS6_PAD_W, BS6_PAD_H, deg, fill=pad_col,
                fill_opacity=".95", stroke="#fff", stroke_width=".8")


def build():
    parts, pads = load_board()
    hl, hw = BS6_BODY_L / 2, BS6_BODY_W / 2
    hot = set()
    for p in parts:
        if p["ref"] == "BT1":
            continue
        if p["x0"] < hl and p["x1"] > -hl and p["y0"] < hw and p["y1"] > -hw:
            hot.add(p["ref"])

    W, H = 1420, 860
    CY, PX = 300, (250, 710, 1170)
    CAP = CY + R_BOARD * SCALE + 30
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="ui-sans-serif,system-ui,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{BG}"/>']

    # ---- panel 1: the incumbent -----------------------------------------
    A = Panel(PX[0], CY)
    A.outline().parts(parts)
    A.rectp(0, 0, MY_SPAN, MY_BODY_W, 0, fill="none", stroke=GOOD,
            stroke_width="1.2", stroke_dasharray="5 4", stroke_opacity=".75")
    for p in pads:
        if p["num"] == "1":
            A.rectp(p["x"], p["y"], p["w"], p["h"], 0, fill=COPPER)
        elif p["circle"] and p["w"] > 5:
            A.circle(p["x"], p["y"], p["w"], fill=COPPER, fill_opacity=".30",
                     stroke=COPPER, stroke_width="1", stroke_dasharray="3 2")
        else:
            A.circle(p["x"], p["y"], p["w"], fill=GOOD)
    A.label(0, -5.6, "Ø8 GND pad", DIM, 9.5)
    A.label(0, 5.6, "6 mask-defined bumps", GOOD, 8.5)
    o.append(A.svg())

    # ---- panel 2: BS-6 as the datasheet intends, centred -----------------
    B = Panel(PX[1], CY)
    B.outline().parts(parts, hot)
    draw_bs6(B)
    o.append(B.svg())
    xl, yl = B.px(15.3, 0)
    o.append(f'<line x1="{xl:.1f}" y1="{yl-64:.1f}" x2="{xl:.1f}" '
             f'y2="{yl-24:.1f}" stroke="{BAD}" stroke-width="1.1"/>')
    o.append(f'<text x="{xl:.1f}" y="{yl-70:.1f}" fill="{BAD}" font-size="10.5" '
             f'text-anchor="middle" font-weight="600">land 1.19 mm off</text>')

    # ---- panel 3: the only land-legal window -----------------------------
    C = Panel(PX[2], CY)
    C.outline().parts(parts)
    j1 = [p for p in parts if p["ref"] == "J1"][0]
    C.rectp((j1["x0"] + j1["x1"]) / 2, (j1["y0"] + j1["y1"]) / 2,
            j1["x1"] - j1["x0"], j1["y1"] - j1["y0"], 0,
            fill=BAD, fill_opacity=".8", stroke="#fff", stroke_width="1")
    draw_bs6(C, ALT_X, ALT_Y, ALT_ROT, pad_col=GOOD)
    o.append(C.svg())
    xj, yj = C.px((j1["x0"] + j1["x1"]) / 2, -17.4)
    o.append(f'<text x="{xj:.1f}" y="{yj:.1f}" fill="#fff" font-size="9" '
             f'text-anchor="middle" font-weight="600">J1</text>')

    # ---- headings + captions --------------------------------------------
    heads = [
        (PX[0], "incumbent — MY-2032-12-R", "C964834 · retainer · 3.6 mm", GOOD,
         "lands on 2 feet, bridges the rest"),
        (PX[1], "candidate — CR2032-BS-6", "C22363833 · socket · 5.5 mm", BAD,
         "lands hang 1.19 mm off the edge"),
        (PX[2], "…rotated 72°, shifted to the tip",
         "the land does fit — 2227 such placements exist", WARN,
         "every one of them sits on J1"),
    ]
    for x, t, sub, col, cap in heads:
        o.append(f'<text x="{x}" y="50" fill="{col}" font-size="15" '
                 f'font-weight="600" text-anchor="middle">{esc(t)}</text>')
        o.append(f'<text x="{x}" y="68" fill="{DIM}" font-size="10.5" '
                 f'text-anchor="middle">{esc(sub)}</text>')
        o.append(f'<text x="{x}" y="{CAP}" fill="{col}" font-size="11.5" '
                 f'text-anchor="middle">{esc(cap)}</text>')
    o.append(f'<text x="{W/2}" y="24" fill="{DIM}" font-size="10.5" '
             f'text-anchor="middle">back of the board, to scale · board Ø30.5 '
             f'(R 15.25) · outline is the real chamfered body, not its bounding '
             f'box · grey = metal solder tabs</text>')

    # ---- elevation -------------------------------------------------------
    ey = 760
    o.append(f'<line x1="60" y1="{ey-172}" x2="{W-60}" y2="{ey-172}" '
             f'stroke="{LINE}" stroke-width="1"/>')
    o.append(f'<text x="60" y="{ey-144}" fill="{FG}" font-size="15" '
             f'font-weight="600">Z height above the PCB</text>')

    def elevation(x0, label, total, cell_inside, col, dim_left=False):
        bw = 300
        o.append(f'<rect x="{x0}" y="{ey}" width="{bw}" height="9" '
                 f'fill="#4a7" fill-opacity=".55"/>')
        o.append(f'<text x="{x0+bw/2}" y="{ey+22}" fill="{DIM}" font-size="9" '
                 f'text-anchor="middle">PCB</text>')
        h = total * ESCALE
        ch_ = CELL_T * ESCALE
        if cell_inside:
            o.append(f'<rect x="{x0+40}" y="{ey-h:.1f}" width="{bw-80}" '
                     f'height="{h:.1f}" rx="3" fill="{col}" fill-opacity=".22" '
                     f'stroke="{col}" stroke-width="1.5"/>')
            o.append(f'<rect x="{x0+62}" y="{ey-ch_-14:.1f}" width="{bw-124}" '
                     f'height="{ch_:.1f}" rx="2" fill="{DIM}" fill-opacity=".65"/>')
            o.append(f'<text x="{x0+bw/2}" y="{ey-ch_/2-8:.1f}" fill="#fff" '
                     f'font-size="9" text-anchor="middle">cell 3.6</text>')
        else:
            o.append(f'<rect x="{x0+70}" y="{ey-ch_:.1f}" width="{bw-140}" '
                     f'height="{ch_:.1f}" rx="2" fill="{DIM}" fill-opacity=".65"/>')
            o.append(f'<text x="{x0+bw/2}" y="{ey-ch_/2+3:.1f}" fill="#fff" '
                     f'font-size="9" text-anchor="middle">cell 3.6</text>')
            o.append(f'<path d="M {x0+34},{ey} L {x0+34},{ey-ch_-4:.1f} '
                     f'Q {x0+bw/2},{ey-ch_-16:.1f} {x0+bw-34},{ey-ch_-4:.1f} '
                     f'L {x0+bw-34},{ey}" fill="none" stroke="{col}" '
                     f'stroke-width="2.6" stroke-linejoin="round"/>')
            for fx in (x0 + 34, x0 + bw - 34):
                o.append(f'<rect x="{fx-13}" y="{ey-4}" width="26" height="5" '
                         f'rx="1" fill="{COPPER}"/>')
            o.append(f'<text x="{x0+bw/2}" y="{ey-ch_-26:.1f}" fill="{col}" '
                     f'font-size="9" text-anchor="middle">spring clip, 2 feet</text>')
        dx = x0 - 16 if dim_left else x0 + bw + 16
        o.append(f'<line x1="{dx}" y1="{ey:.1f}" x2="{dx}" y2="{ey-h:.1f}" '
                 f'stroke="{col}" stroke-width="1.2"/>')
        o.append(f'<text x="{dx-8 if dim_left else dx+8}" y="{ey-h/2+4:.1f}" '
                 f'fill="{col}" font-size="13" font-weight="600" '
                 f'text-anchor="{"end" if dim_left else "start"}">{total} mm</text>')
        o.append(f'<text x="{x0+bw/2}" y="{ey+40}" fill="{FG}" font-size="11.5" '
                 f'text-anchor="middle">{esc(label)}</text>')

    elevation(210, "MY-2032-12-R — cell rests on the board", MY_H, False, GOOD,
              dim_left=True)
    elevation(830, "CR2032-BS-6 — cell rides inside the socket", BS6_H, True, BAD)
    top_my, top_bs = ey - MY_H * ESCALE, ey - BS6_H * ESCALE
    for yy, col in ((top_my, GOOD), (top_bs, BAD)):
        o.append(f'<line x1="510" y1="{yy:.1f}" x2="850" y2="{yy:.1f}" '
                 f'stroke="{col}" stroke-width="1" stroke-dasharray="4 4" '
                 f'stroke-opacity=".55"/>')
    o.append(f'<line x1="680" y1="{top_my:.1f}" x2="680" y2="{top_bs:.1f}" '
             f'stroke="{BAD}" stroke-width="1.6"/>')
    o.append(f'<text x="680" y="{top_bs-12:.1f}" fill="{BAD}" font-size="14" '
             f'font-weight="600" text-anchor="middle">+1.9 mm — 53% taller</text>')
    o.append(f'<text x="{W/2}" y="{ey+72}" fill="{DIM}" font-size="10.5" '
             f'text-anchor="middle">pocket is drawn for a 3.2 mm CR2032; the '
             f'fitted RJD2032C1 is 3.6 mm — a moulded socket cannot splay the '
             f'way a spring clip does</text>')

    o.append("</svg>")
    OUT.write_text("\n".join(o))
    print(f"wrote {OUT}")
    print(f"  body-fouled parts (true outline): {len(hot)} — "
          f"{', '.join(sorted(hot))}")


if __name__ == "__main__":
    build()
