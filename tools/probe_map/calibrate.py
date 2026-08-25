#!/usr/bin/env python3
"""Calibrate mm->px for the orthographic renders via alpha extents,
then draw the board outline over each render to verify alignment."""
import json

import numpy as np
from PIL import Image, ImageDraw

g = json.load(open("geom.json"))
outline = np.array(g["outline"])
ox0, ox1 = outline[:, 0].min(), outline[:, 0].max()
oy0, oy1 = outline[:, 1].min(), outline[:, 1].max()
print(f"outline mm: x {ox0:.3f}..{ox1:.3f}  y {oy0:.3f}..{oy1:.3f}")

cal = {}
for side in ("top", "bottom"):
    im = Image.open(f"probe_{side}.png")
    a = np.array(im)[:, :, 3]
    rows = np.where((a > 200).any(axis=1))[0]
    cols = np.where((a > 200).any(axis=0))[0]
    print(f"{side}: img {im.size}, content rows {rows[0]}..{rows[-1]}, "
          f"cols {cols[0]}..{cols[-1]}")
    # max-width row = the circular body's diameter
    widths = []
    for r in rows:
        c = np.where(a[r] > 200)[0]
        widths.append((c[-1] - c[0], r, c[0], c[-1]))
    wmax, rmax, cl, cr = max(widths)
    # scale from the circle diameter; the widest chord spans ox0..ox1
    s = wmax / (ox1 - ox0)
    cx = (cl + cr) / 2  # maps to board x center (100)
    # bottom of the circle (max y in board coords) -> lowest content row
    ybot_px = rows[-1]
    if side == "top":
        # x_px = cx + (x-100)*s ; y_px = ybot_px - (oy1 - y)*s
        def fwd(x, y, s=s, cx=cx, yb=ybot_px):
            return cx + (x - 100) * s, yb - (oy1 - y) * s
        mirror = False
    else:
        def fwd(x, y, s=s, cx=cx, yb=ybot_px):
            return cx - (x - 100) * s, yb - (oy1 - y) * s
        mirror = True
    cal[side] = {"s": s, "cx": cx, "ybot_px": int(ybot_px),
                 "oy1": oy1, "mirror": mirror}
    print(f"  scale {s:.3f} px/mm, cx {cx:.1f}, ybot {ybot_px}, "
          f"widest row {rmax} ({wmax}px)")
    # verify: draw outline + a few landmark crosses
    im2 = im.convert("RGB")
    d = ImageDraw.Draw(im2)
    pts = [fwd(x, y) for x, y in outline]
    d.line(pts + pts[:1], fill=(255, 0, 255), width=3)
    marks = {"top": [("U1", 100, 99.5), ("Y1", 100, 91.98),
                     ("L1", 98.0, 106.82), ("C16", 107.94, 104.84)],
             "bottom": [("BT1c", 100, 100), ("TP1", 88.2, 95.0),
                        ("SW2", 91.34, 89.62), ("clipR", 112.4, 100)]}
    for name, x, y in marks[side]:
        px, py = fwd(x, y)
        d.line([(px - 18, py), (px + 18, py)], fill=(0, 255, 255), width=3)
        d.line([(px, py - 18), (px, py + 18)], fill=(0, 255, 255), width=3)
    im2.save(f"verify_{side}.png")

json.dump(cal, open("cal.json", "w"))
print("wrote cal.json, verify_top.png, verify_bottom.png")
