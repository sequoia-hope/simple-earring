#!/usr/bin/env python3
"""Dump probe-relevant geometry from the ordered-rev board as JSON."""
import json
import sys

import pcbnew

PCB = sys.argv[1]
board = pcbnew.LoadBoard(PCB)

NM = 1e-6  # nm -> mm

bbox = board.GetBoardEdgesBoundingBox()
out = {
    "bbox_mm": {
        "x0": bbox.GetLeft() * NM, "y0": bbox.GetTop() * NM,
        "x1": bbox.GetRight() * NM, "y1": bbox.GetBottom() * NM,
    },
    "outline": [],
    "footprints": {},
    "pads": [],
}

# board outline polygon (for overlay-calibration check)
poly = pcbnew.SHAPE_POLY_SET()
board.GetBoardPolygonOutlines(poly)
if poly.OutlineCount():
    o = poly.Outline(0)
    out["outline"] = [
        [o.CPoint(i).x * NM, o.CPoint(i).y * NM] for i in range(o.PointCount())
    ]

REFS = {"U1", "U2", "U3", "U4", "U5", "U6", "J1", "BT1", "SW1", "SW2",
        "L1", "C11", "C12", "C16", "C17", "C18", "C19", "C28",
        "R2", "R3", "R6", "R7", "R8", "TP1", "TP2", "TP3", "X1", "Y1"}
NETS = {"VBUS", "VBATT", "3V3", "PWR_EN", "RUN", "VDD_CORE", "GND",
        "USB_C_DP", "USB_C_DN", "USB_DP", "USB_DM", "BOOTSEL", "LED_EN",
        "VLED"}

for fp in board.GetFootprints():
    ref = fp.GetReference()
    p = fp.GetPosition()
    side = "B" if fp.GetLayer() == pcbnew.B_Cu else "F"
    if ref in REFS:
        out["footprints"][ref] = {
            "x": p.x * NM, "y": p.y * NM, "side": side,
            "rot": fp.GetOrientationDegrees(),
            "val": fp.GetValue(),
        }
    for pad in fp.Pads():
        net = pad.GetNetname()
        if net in NETS and (ref in REFS):
            pp = pad.GetPosition()
            sz = pad.GetSize()
            out["pads"].append({
                "ref": ref, "pad": pad.GetNumber(), "net": net,
                "x": pp.x * NM, "y": pp.y * NM,
                "w": sz.x * NM, "h": sz.y * NM,
                "side": side,
                "tht": pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH,
            })

print(json.dumps(out))
