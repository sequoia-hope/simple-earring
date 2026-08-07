"""Silk art applied to generated boards (see also the tracked board).

Heart outline lifted from the rp2350-motor-controller back silk (its
B.Silkscreen zone), stored center-relative, placed below the MCU.
URL arcs: two concentric rings on the back south rim, outside the
inserted battery disc (r10), reading in order from the back. Hand
texts by Sequoia (Aug 2026), replicated verbatim.
"""
import math

import pcbnew

mm = pcbnew.FromMM

# center-relative heart outline, mm (141 pts, decimated from 562)
HEART = [
    (0.6485, -1.4284), (0.5258, -1.3933), (0.4381, -1.3582), (0.3856, -1.3232),
    (0.3155, -1.2881), (0.2629, -1.2531), (0.2278, -1.2180), (0.1753, -1.1830),
    (0.1227, -1.1479), (0.0876, -1.1129), (0.0526, -1.0778), (0.0175, -1.0428),
    (-0.0351, -1.0778), (-0.0701, -1.1129), (-0.1052, -1.1479), (-0.1577, -1.1830),
    (-0.1928, -1.2180), (-0.2454, -1.2531), (-0.2979, -1.2881), (-0.3505, -1.3232),
    (-0.4031, -1.3582), (-0.4907, -1.3933), (-0.5784, -1.4284), (-0.9990, -1.4284),
    (-1.1392, -1.3933), (-1.2268, -1.3582), (-1.2969, -1.3232), (-1.3670, -1.2881),
    (-1.4021, -1.2531), (-1.4371, -1.2180), (-1.4897, -1.1655), (-1.5247, -1.1304),
    (-1.5598, -1.0778), (-1.5948, -1.0077), (-1.6299, -0.9376), (-1.6649, -0.7974),
    (-1.7000, -0.4820), (-1.6649, -0.3067), (-1.6299, -0.2015), (-1.5948, -0.1314),
    (-1.5598, -0.0789), (-1.5247, -0.0088), (-1.4897, 0.0263), (-1.4546, 0.0789),
    (-1.4196, 0.1314), (-1.3845, 0.1665), (-1.3495, 0.2015), (-1.3144, 0.2366),
    (-1.2794, 0.2892), (-1.2268, 0.3242), (-1.1918, 0.3593), (-1.1567, 0.3943),
    (-1.1216, 0.4294), (-1.0866, 0.4644), (-1.0515, 0.4995), (-1.0165, 0.5345),
    (-0.9814, 0.5696), (-0.9464, 0.6046), (-0.9113, 0.6397), (-0.8763, 0.6747),
    (-0.8412, 0.7098), (-0.8062, 0.7448), (-0.7536, 0.7799), (-0.7186, 0.8149),
    (-0.6835, 0.8500), (-0.6485, 0.8851), (-0.6134, 0.9201), (-0.5784, 0.9552),
    (-0.5433, 0.9902), (-0.5082, 1.0253), (-0.4732, 1.0603), (-0.4381, 1.0954),
    (-0.4031, 1.1304), (-0.3680, 1.1655), (-0.3330, 1.2005), (-0.2804, 1.2356),
    (-0.2454, 1.2706), (-0.2103, 1.3057), (-0.1753, 1.3407), (-0.1402, 1.3758),
    (-0.1052, 1.4108), (-0.0701, 1.4459), (0.0351, 1.4459), (0.0876, 1.4108),
    (0.1227, 1.3758), (0.1577, 1.3407), (0.1928, 1.3057), (0.2278, 1.2706),
    (0.2629, 1.2356), (0.2979, 1.2005), (0.3505, 1.1655), (0.3856, 1.1304),
    (0.4206, 1.0954), (0.4557, 1.0603), (0.4907, 1.0253), (0.5258, 0.9902),
    (0.5608, 0.9552), (0.5959, 0.9201), (0.6309, 0.8851), (0.6660, 0.8500),
    (0.7010, 0.8149), (0.7361, 0.7799), (0.7711, 0.7448), (0.8237, 0.7098),
    (0.8588, 0.6747), (0.8938, 0.6397), (0.9289, 0.6046), (0.9639, 0.5696),
    (0.9990, 0.5345), (1.0340, 0.4995), (1.0691, 0.4644), (1.1041, 0.4294),
    (1.1392, 0.3943), (1.1742, 0.3593), (1.2093, 0.3242), (1.2619, 0.2716),
    (1.3144, 0.2366), (1.3495, 0.1840), (1.3845, 0.1490), (1.4196, 0.0964),
    (1.4546, 0.0613), (1.4897, 0.0088), (1.5247, -0.0438), (1.5598, -0.1139),
    (1.5948, -0.1665), (1.6299, -0.2541), (1.6649, -0.3593), (1.7000, -0.7098),
    (1.6649, -0.8851), (1.6299, -0.9727), (1.5948, -1.0428), (1.5598, -1.0954),
    (1.5247, -1.1479), (1.4897, -1.1830), (1.4546, -1.2356), (1.4021, -1.2706),
    (1.3670, -1.3057), (1.2969, -1.3407), (1.2268, -1.3758), (1.1392, -1.4108),
    (0.9990, -1.4459),]

HEART_AT = (101.5, 105.491)   # board position of heart center
HEART_SCALE = 1.0             # points are stored already scaled (3.4mm wide)

# (text, (x, y), angle_deg) - F.Silkscreen, 0.8mm, left/bottom justified
HAND_TEXTS = [
    ('Sequoia Hope', (90.519164, 92.822526), 30.0),
    ('Alexander', (91.747502, 93.392809), 30.0),
    ('Be Gay', (90.567161, 97.687147), 60.0),
    ('Do Crimes', (107.15, 93.24), 300.0),
    ('Love Everyone', (102.102506, 86.619369), 315.0),
]

# back URL arcs: (text, radius, per-char advance mm, center offset deg)
# bounded by TP3 pad (-53.4 deg from south) and R12 pad (+52.0)
ARC_CENTER = (100.0, 100.0)   # battery + board-disc center
ARC_H = 1.0
ARCS = [
    ('github.com/', 11.8, 0.92, -0.7),
    ('sequoia-hope/simple-earring', 13.2, 0.88, -0.7),
]


def add_art(board):
    # heart, filled poly on F.Silkscreen
    chain = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in HEART:
        chain.Append(mm(HEART_AT[0] + x * HEART_SCALE),
                     mm(HEART_AT[1] + y * HEART_SCALE))
    chain.SetClosed(True)
    poly = pcbnew.SHAPE_POLY_SET()
    poly.AddOutline(chain)
    heart = pcbnew.PCB_SHAPE(board)
    heart.SetShape(pcbnew.SHAPE_T_POLY)
    heart.SetPolyShape(poly)
    heart.SetLayer(pcbnew.F_SilkS)
    heart.SetFilled(True)
    heart.SetWidth(0)
    board.Add(heart)

    # hand texts, front
    for text, (x, y), ang in HAND_TEXTS:
        t = pcbnew.PCB_TEXT(board)
        t.SetText(text)
        t.SetLayer(pcbnew.F_SilkS)
        t.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        t.SetTextHeight(mm(0.8))
        t.SetTextWidth(mm(0.8))
        t.SetTextThickness(mm(0.15))
        t.SetTextAngle(pcbnew.EDA_ANGLE(ang, pcbnew.DEGREES_T))
        t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_BOTTOM)
        board.Add(t)

    # URL arcs, back, per-char mirrored text (coin-bottom style: chars
    # left->right seen from the back, glyph tops toward center)
    cx, cy = ARC_CENTER
    for text, r, adv, off in ARCS:
        step = math.degrees(adv / r)
        n = len(text)
        for i, ch in enumerate(text):
            s = math.radians((i - (n - 1) / 2) * step + off)
            u, v = r * math.sin(s), r * math.cos(s)
            t = pcbnew.PCB_TEXT(board)
            t.SetText(ch)
            t.SetLayer(pcbnew.B_SilkS)
            t.SetPosition(pcbnew.VECTOR2I(mm(cx - u), mm(cy + v)))
            t.SetTextHeight(mm(ARC_H))
            t.SetTextWidth(mm(ARC_H))
            t.SetTextThickness(mm(0.15))
            t.SetMirrored(True)
            t.SetTextAngle(pcbnew.EDA_ANGLE(-math.degrees(s), pcbnew.DEGREES_T))
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
            t.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
            board.Add(t)
