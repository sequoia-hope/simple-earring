#!/usr/bin/env python3
"""Generate the R8 rework diagrams in out/rework/ from the ORDERED board.

The physical boards being reworked are the ordered revision (commit
ORDERED_REV), NOT the working tree — out/earring.kicad_pcb is regenerated
by the build scripts and can legitimately be mid-generation (every
footprint stacked at one point), which would place R8 wrongly. So the
geometry is read straight out of git.

Front view: KiCad's +y is down and SVG's +y is down, so a front-side view
maps through with no flip.

    python3 scripts/gen_rework_svg.py
"""
import json, math, pathlib, subprocess, tempfile

import pcbnew

ORDERED_REV = "43eadc1"
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "rework"
OUT.mkdir(parents=True, exist_ok=True)


def load_ordered_geometry():
    """Pull out/earring.kicad_pcb at ORDERED_REV and extract what we draw."""
    blob = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ORDERED_REV}:out/earring.kicad_pcb"],
        capture_output=True, check=True).stdout
    with tempfile.NamedTemporaryFile(suffix=".kicad_pcb", delete=False) as fh:
        fh.write(blob)
        tmp = fh.name
    b = pcbnew.LoadBoard(tmp)
    mm = lambda v: v / 1e6
    edges = []
    for d in b.GetDrawings():
        if d.GetLayerName() != "Edge.Cuts":
            continue
        st = d.GetShapeStr()
        e = {"shape": st}
        if st.lower().startswith("arc"):
            c = d.GetCenter()
            e.update(cx=mm(c.x), cy=mm(c.y), r=mm(d.GetRadius()),
                     sx=mm(d.GetStart().x), sy=mm(d.GetStart().y),
                     ex=mm(d.GetEnd().x), ey=mm(d.GetEnd().y))
        else:
            e.update(sx=mm(d.GetStart().x), sy=mm(d.GetStart().y),
                     ex=mm(d.GetEnd().x), ey=mm(d.GetEnd().y))
        edges.append(e)
    fps = []
    for f in b.GetFootprints():
        pads, xs, ys = [], [], []
        for p in f.Pads():
            pp, sz = p.GetPosition(), p.GetSize()
            pads.append(dict(name=p.GetPadName(), x=mm(pp.x), y=mm(pp.y),
                             w=mm(sz.x), h=mm(sz.y), net=p.GetNetname()))
            xs += [mm(pp.x) - mm(sz.x) / 2, mm(pp.x) + mm(sz.x) / 2]
            ys += [mm(pp.y) - mm(sz.y) / 2, mm(pp.y) + mm(sz.y) / 2]
        pos = f.GetPosition()
        fps.append(dict(ref=f.GetReference(), val=f.GetValue(),
                        x=mm(pos.x), y=mm(pos.y), rot=f.GetOrientationDegrees(),
                        layer=f.GetLayerName(), pads=pads,
                        x0=min(xs) if xs else mm(pos.x),
                        x1=max(xs) if xs else mm(pos.x),
                        y0=min(ys) if ys else mm(pos.y),
                        y1=max(ys) if ys else mm(pos.y)))
    if len({(f["x"], f["y"]) for f in fps}) < 10:
        raise SystemExit(f"{ORDERED_REV} board looks un-placed — wrong revision?")
    return dict(edges=edges, fps=fps)


G = load_ordered_geometry()
FPS = {f["ref"]: f for f in G["fps"]}
R8 = FPS["R8"]

BG, PART, PARTL = "#15171d", "#2f3540", "#8d97a8"
PART = "#2f3540"
LEDC = "#3a4250"
HI, HI2 = "#ff4d4d", "#ffd166"
TXT, DIM = "#e6e9ef", "#8d97a8"


def outline_path():
    lines = [e for e in G["edges"] if e["shape"] == "Line"]
    arc = [e for e in G["edges"] if e["shape"] == "Arc"][0]
    # the three straight segments form the point at the top, then one big
    # arc closes the round bottom (sweep 247deg -> large-arc, clockwise)
    p = f"M {lines[0]['sx']:.3f},{lines[0]['sy']:.3f} "
    for ln in lines:
        p += f"L {ln['ex']:.3f},{ln['ey']:.3f} "
    p += f"A {arc['r']:.3f},{arc['r']:.3f} 0 1 1 {arc['ex']:.3f},{arc['ey']:.3f} Z"
    return p


def part_rect(f, pad=0.10):
    x0, y0 = f["x0"] - pad, f["y0"] - pad
    return x0, y0, (f["x1"] - f["x0"]) + 2 * pad, (f["y1"] - f["y0"]) + 2 * pad


def svg_header(vb, w, h, extra=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" '
            f'width="{w}" height="{h}" font-family="DejaVu Sans, sans-serif">'
            f'<rect x="-9999" y="-9999" width="19998" height="19998" fill="{BG}"/>{extra}')


# ---------------------------------------------------------------- board
def board_svg():
    # Room on both flanks for callouts placed OUTSIDE the outline: labels
    # laid over the LED ring collide with each other and with the parts.
    x0, y0, x1, y1 = 68.0, 74.0, 143.0, 121.0
    W, H = x1 - x0, y1 - y0
    s = [svg_header(f"{x0} {y0} {W} {H}", 980, int(980 * H / W))]
    s.append(f'<path d="{outline_path()}" fill="#1c2029" stroke="{DIM}" '
             f'stroke-width="0.18"/>')
    for f in G["fps"]:
        if f["layer"] != "F.Cu" or f["ref"] == "R8":
            continue
        rx, ry, rw, rh = part_rect(f)
        col = LEDC if f["ref"].startswith("LED") else PART
        s.append(f'<rect x="{rx:.3f}" y="{ry:.3f}" width="{rw:.3f}" '
                 f'height="{rh:.3f}" rx="0.12" fill="{col}"/>')
    # landmarks: box the part, run a leader out to a label clear of the board
    marks = [("J1", "USB-C", 100.0, 77.4, "middle"),
             ("SW2", "power switch", 80.5, 87.0, "end"),
             ("TP1", "TP1 (RUN)", 80.5, 95.5, "end"),
             ("U1", "RP2350", 80.5, 104.0, "end"),
             ("U4", "U4 LED switch", 121.0, 98.6, "start"),
             ("U2", "U2 charger", 121.0, 108.0, "start")]
    for ref, label, lx, ly, anch in marks:
        f = FPS.get(ref)
        if not f:
            continue
        rx, ry, rw, rh = part_rect(f, 0.15)
        s.append(f'<rect x="{rx:.3f}" y="{ry:.3f}" width="{rw:.3f}" '
                 f'height="{rh:.3f}" rx="0.12" fill="none" stroke="{PARTL}" '
                 f'stroke-width="0.14"/>')
        ax = rx + (rw if anch == "start" else (0 if anch == "end" else rw / 2))
        ay = ry + (0 if anch == "middle" else rh / 2)
        s.append(f'<line x1="{ax:.2f}" y1="{ay:.2f}" x2="{lx:.2f}" y2="{ly:.2f}" '
                 f'stroke="{PARTL}" stroke-width="0.09" opacity="0.75"/>')
        off = -0.6 if anch == "middle" else 0.45
        s.append(f'<text x="{lx:.2f}" y="{ly+off:.2f}" fill="{PARTL}" '
                 f'font-size="1.6" text-anchor="{anch}">{label}</text>')
    # R8: the star of the diagram — halo, part, leader, boxed callout
    rx, ry, rw, rh = part_rect(R8, 0.12)
    s.append(f'<circle cx="{R8["x"]:.3f}" cy="{R8["y"]:.3f}" r="2.6" '
             f'fill="none" stroke="{HI}" stroke-width="0.22" opacity="0.9"/>')
    s.append(f'<circle cx="{R8["x"]:.3f}" cy="{R8["y"]:.3f}" r="4.1" '
             f'fill="none" stroke="{HI}" stroke-width="0.10" opacity="0.35"/>')
    s.append(f'<rect x="{rx:.3f}" y="{ry:.3f}" width="{rw:.3f}" height="{rh:.3f}" '
             f'rx="0.10" fill="{HI}"/>')
    s.append(f'<line x1="{R8["x"]+2.7:.2f}" y1="{R8["y"]-1.9:.2f}" x2="120.5" '
             f'y2="88.4" stroke="{HI}" stroke-width="0.18"/>')
    s.append(f'<rect x="120.5" y="80.6" width="21.2" height="9.2" rx="0.7" '
             f'fill="#241a1c" stroke="{HI}" stroke-width="0.18"/>')
    s.append(f'<text x="122.0" y="84.2" fill="{HI}" font-size="2.6" '
             f'font-weight="bold">R8</text>')
    s.append(f'<text x="122.0" y="87.0" fill="{TXT}" font-size="1.85">'
             f'22k → 15k</text>')
    s.append(f'<text x="122.0" y="89.1" fill="{DIM}" font-size="1.4">'
             f'0402 · front side</text>')
    s.append(f'<text x="{(x0+x1)/2:.1f}" y="{y1-1.4:.1f}" fill="{DIM}" '
             f'font-size="1.7" text-anchor="middle">FRONT (component side) '
             f'— the battery clip is on the back</text>')
    s.append("</svg>")
    return "\n".join(s)


# --------------------------------------------------------------- detail
def detail_svg():
    cx, cy, R = R8["x"], R8["y"], 4.6
    x0, y0, W, H = cx - R, cy - R, 2 * R, 2 * R
    s = [svg_header(f"{x0} {y0} {W} {H}", 560, 560)]
    # faint mm grid for scale
    g = math.floor(x0)
    while g < x0 + W:
        s.append(f'<line x1="{g}" y1="{y0}" x2="{g}" y2="{y0+H}" '
                 f'stroke="#20242d" stroke-width="0.03"/>')
        g += 1
    g = math.floor(y0)
    while g < y0 + H:
        s.append(f'<line x1="{x0}" y1="{g}" x2="{x0+W}" y2="{g}" '
                 f'stroke="#20242d" stroke-width="0.03"/>')
        g += 1
    BAR = 1.85                     # reserved caption strip along the bottom
    for f in G["fps"]:
        if f["ref"] == "R8":
            continue
        if not (x0 - 1 < f["x"] < x0 + W + 1 and y0 - 1 < f["y"] < y0 + H + 1):
            continue
        back = f["layer"] == "B.Cu"
        for p in f["pads"]:
            s.append(f'<rect x="{p["x"]-p["w"]/2:.3f}" y="{p["y"]-p["h"]/2:.3f}" '
                     f'width="{p["w"]:.3f}" height="{p["h"]:.3f}" rx="0.05" '
                     f'fill="{"#242a34" if back else "#39414f"}"/>')
        rx, ry, rw, rh = part_rect(f, 0.05)
        dash = ' stroke-dasharray="0.15,0.12"' if back else ""
        s.append(f'<rect x="{rx:.3f}" y="{ry:.3f}" width="{rw:.3f}" height="{rh:.3f}" '
                 f'rx="0.08" fill="none" stroke="{"#2b313b" if back else "#4c5666"}" '
                 f'stroke-width="0.05"{dash}/>')
        # LEDs go unlabelled — 45 of them would bury the part that matters.
        # Skip labels near the edges (clipped) and inside the caption strip.
        if f["ref"].startswith("LED"):
            continue
        ty = f["y"] - rh / 2 - 0.16
        if not (x0 + 0.7 < f["x"] < x0 + W - 0.7 and y0 + 0.5 < ty < y0 + H - BAR - 0.2):
            continue
        lbl = f["ref"] + ("" if not back else " (back)")
        s.append(f'<text x="{f["x"]:.2f}" y="{ty:.2f}" '
                 f'fill="{"#5b6472" if back else PARTL}" font-size="0.42" '
                 f'text-anchor="middle">{lbl}</text>')
    # R8: dashed box kept tight, net names stacked above/below its own pads
    # so they never collide with C17 to the west or C52 to the south-east.
    s.append(f'<rect x="{cx-1.15:.2f}" y="{cy-1.95:.2f}" width="2.3" height="3.9" '
             f'rx="0.2" fill="none" stroke="{HI}" stroke-width="0.09" '
             f'stroke-dasharray="0.28,0.2"/>')
    for p in R8["pads"]:
        s.append(f'<rect x="{p["x"]-p["w"]/2:.3f}" y="{p["y"]-p["h"]/2:.3f}" '
                 f'width="{p["w"]:.3f}" height="{p["h"]:.3f}" rx="0.05" fill="{HI2}"/>')
    top = min(R8["pads"], key=lambda p: p["y"])
    bot = max(R8["pads"], key=lambda p: p["y"])
    s.append(f'<text x="{cx:.2f}" y="{top["y"]-top["h"]/2-0.20:.2f}" fill="{HI2}" '
             f'font-size="0.40" text-anchor="middle">{top["net"]}</text>')
    s.append(f'<text x="{cx:.2f}" y="{bot["y"]+bot["h"]/2+0.48:.2f}" fill="{HI2}" '
             f'font-size="0.40" text-anchor="middle">{bot["net"]}</text>')
    s.append(f'<rect x="{cx-0.25:.3f}" y="{cy-0.5:.3f}" width="0.5" height="1.0" '
             f'rx="0.06" fill="{HI}"/>')
    # caption strip: opaque, so nothing under it can collide with the text
    by = y0 + H - BAR
    s.append(f'<rect x="{x0}" y="{by:.2f}" width="{W}" height="{BAR}" fill="#0f1116"/>')
    s.append(f'<line x1="{x0}" y1="{by:.2f}" x2="{x0+W}" y2="{by:.2f}" '
             f'stroke="#252a33" stroke-width="0.04"/>')
    s.append(f'<text x="{x0+0.45:.2f}" y="{by+0.74:.2f}" fill="{HI}" font-size="0.56" '
             f'font-weight="bold">R8 — lift this one</text>')
    s.append(f'<text x="{x0+0.45:.2f}" y="{by+1.46:.2f}" fill="{TXT}" '
             f'font-size="0.46">0402 · 1.0 × 0.5 mm</text>')
    sb0, sb1, sby = x0 + W - 2.7, x0 + W - 0.7, by + 1.30
    s.append(f'<line x1="{sb0:.2f}" y1="{sby:.2f}" x2="{sb1:.2f}" y2="{sby:.2f}" '
             f'stroke="{DIM}" stroke-width="0.07"/>')
    for t in (sb0, sb1):
        s.append(f'<line x1="{t:.2f}" y1="{sby-0.15:.2f}" x2="{t:.2f}" '
                 f'y2="{sby+0.15:.2f}" stroke="{DIM}" stroke-width="0.07"/>')
    s.append(f'<text x="{(sb0+sb1)/2:.2f}" y="{sby-0.30:.2f}" fill="{DIM}" '
             f'font-size="0.42" text-anchor="middle">2 mm</text>')
    s.append("</svg>")
    return "\n".join(s)


# ------------------------------------------------------------ schematic
def schem_svg():
    """PROG -> R8 -> GND, the one net the rework touches."""
    s = [svg_header("0 0 440 104", 880, 208)]
    W = f'stroke="{PARTL}" stroke-width="1.7" fill="none"'
    s.append(f'<rect x="18" y="20" width="98" height="64" rx="6" fill="#222833" '
             f'stroke="{PARTL}" stroke-width="1.7"/>')
    s.append(f'<text x="67" y="44" fill="{TXT}" font-size="15" text-anchor="middle" '
             f'font-weight="bold">U2</text>')
    s.append(f'<text x="67" y="61" fill="{DIM}" font-size="11.5" text-anchor="middle">'
             f'LGS4056H</text>')
    s.append(f'<text x="67" y="76" fill="{DIM}" font-size="10" text-anchor="middle">'
             f'charger</text>')
    s.append(f'<line x1="116" y1="52" x2="171" y2="52" {W}/>')
    s.append(f'<text x="143" y="42" fill="{DIM}" font-size="10.5" '
             f'text-anchor="middle">PROG</text>')
    s.append(f'<text x="143" y="30" fill="{DIM}" font-size="9.5" '
             f'text-anchor="middle">(pin 2)</text>')
    s.append(f'<rect x="171" y="36" width="42" height="32" rx="4" fill="#2b2226" '
             f'stroke="{HI}" stroke-width="2.2"/>')
    s.append(f'<text x="192" y="28" fill="{HI}" font-size="13.5" text-anchor="middle" '
             f'font-weight="bold">R8</text>')
    s.append(f'<text x="192" y="58" fill="{TXT}" font-size="14" text-anchor="middle" '
             f'font-weight="bold">15k</text>')
    s.append(f'<text x="192" y="82" fill="{DIM}" font-size="10.5" '
             f'text-anchor="middle">was 22k</text>')
    s.append(f'<line x1="213" y1="52" x2="256" y2="52" {W}/>')
    s.append(f'<line x1="256" y1="52" x2="256" y2="60" {W}/>')
    for i, half in enumerate((13, 8, 3.5)):
        s.append(f'<line x1="{256-half}" y1="{60+i*5}" x2="{256+half}" '
                 f'y2="{60+i*5}" stroke="{PARTL}" stroke-width="2"/>')
    s.append(f'<line x1="292" y1="18" x2="292" y2="90" stroke="#2a3039" '
             f'stroke-width="1.4"/>')
    s.append(f'<text x="308" y="32" fill="{TXT}" font-size="12.5">'
             f'I = 900 / R(kΩ)  mA</text>')
    s.append(f'<text x="308" y="56" fill="{DIM}" font-size="12">'
             f'22k → 41 mA  (today)</text>')
    s.append(f'<text x="308" y="78" fill="{HI}" font-size="12" '
             f'font-weight="bold">15k → 60 mA</text>')
    s.append("</svg>")
    return "\n".join(s)


(OUT / "board.svg").write_text(board_svg())
(OUT / "detail.svg").write_text(detail_svg())
(OUT / "schem.svg").write_text(schem_svg())
print("wrote", OUT / "board.svg", OUT / "detail.svg", OUT / "schem.svg")
