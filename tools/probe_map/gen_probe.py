#!/usr/bin/env python3
"""Generate out/probe/ — annotated meter probe map for USB bring-up.

Renders (ordered rev) + calibrated mm->px transform -> SVG-overlaid
board images, ladder table, and zoomed closeup cards.
"""
import html
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

SCRATCH = Path(__file__).resolve().parent
OUT = Path("/home/sequoia/pcb/simple_earring/out/probe")
OUT.mkdir(parents=True, exist_ok=True)

cal = json.load(open(SCRATCH / "cal.json"))
W, H = 1376, 1624  # render size


def fwd(side, x, y):
    c = cal[side]
    px = c["cx"] + (x - 100) * c["s"] * (-1 if c["mirror"] else 1)
    py = c["ybot_px"] - (c["oy1"] - y) * c["s"]
    return px, py


COLORS = {
    "GND":  "#e8e8e8",
    "VBUS": "#ff5c39",
    "VBATT": "#ffb02e",
    "PWR_EN": "#ff6ec7",
    "3V3":  "#3ddcff",
    "RUN":  "#4ade80",
    "CORE": "#b78bff",
    "DATA": "#6b9bff",
}

# (side, step, net, x_mm, y_mm, ring_r_px, badge_angle_deg, badge_dist)
# badge angle: 0 = east (image space), 90 = south
MARKERS = [
    # front (render: top)
    ("top", "G", "GND",   95.67, 85.12, 30, 200, 75),   # J1 THT shell leg
    ("top", "1", "VBUS",  107.94, 105.62, 26, 340, 70),  # C16.1
    ("top", "2", "VBATT", 107.20, 102.60, 26, 20, 70),   # C17.1
    ("top", "4", "3V3",   91.43, 104.10, 26, 160, 70),   # C19.1
    ("top", "6", "CORE",  98.70, 106.82, 28, 100, 72),   # L1.1
    # back (render: bottom)
    ("bottom", "G", "GND", 100.00, 100.00, 64, 90, 110),  # BT1 center pad
    ("bottom", "1", "VBUS", 103.14, 88.38, 24, 215, 70),  # C28.1
    ("bottom", "2", "VBATT", 112.40, 100.00, 44, 180, 90),  # clip pad (img L)
    ("bottom", "2", "VBATT", 87.60, 100.00, 44, 0, 90),    # clip pad (img R)
    ("bottom", "3", "PWR_EN", 93.17, 89.95, 24, 35, 75),   # SW2.2
    ("bottom", "5", "RUN", 88.20, 95.00, 32, 0, 80),       # TP1
    ("bottom", "7", "DATA", 97.44, 88.53, 58, 115, 105),   # R6+R7 pair
]

# secondary dashed ring: the J1 D+/D- pads (continuity partner of step 7)
DASHED = [("bottom", "DATA", 100.0, 85.88, 40)]

# (side, text, x_mm, y_mm, dx, dy, anchor)  small gray context labels
CONTEXT = [
    ("top", "RP2354A", 100.0, 99.5, 0, 8, "middle"),
    ("top", "12 MHz xtal", 100.0, 91.98, 85, 0, "start"),
    ("top", "BOOTSEL", 100.0, 87.6, 0, -55, "middle"),
    ("top", "charger", 105.5, 105.0, 30, 78, "start"),
    ("top", "LDO", 93.4, 103.4, -12, -48, "end"),
    ("bottom", "USB-C", 100.0, 83.41, 0, -20, "middle"),
    ("bottom", "ESD", 100.0, 88.5, 0, 52, "middle"),
    ("bottom", "power switch", 91.34, 89.62, 118, 6, "start"),
    ("bottom", "IMU", 108.66, 89.62, -10, -60, "middle"),
    ("bottom", "TP2 swclk", 88.37, 104.67, -55, 8, "end"),
    ("bottom", "TP3 swdio", 88.54, 107.21, -55, 8, "end"),
]


def svg_markers(side):
    import math
    parts = []
    for s, step, net, x, y, r, ang, dist in MARKERS:
        if s != side:
            continue
        px, py = fwd(side, x, y)
        col = COLORS[net]
        a = math.radians(ang)
        bx, by = px + dist * math.cos(a), py + dist * math.sin(a)
        ex, ey = px + (r + 4) * math.cos(a), py + (r + 4) * math.sin(a)
        parts.append(
            f'<circle cx="{px:.0f}" cy="{py:.0f}" r="{r}" fill="none" '
            f'stroke="#000" stroke-opacity=".55" stroke-width="9"/>'
            f'<circle cx="{px:.0f}" cy="{py:.0f}" r="{r}" fill="none" '
            f'stroke="{col}" stroke-width="4.5"/>'
            f'<line x1="{ex:.0f}" y1="{ey:.0f}" x2="{bx:.0f}" y2="{by:.0f}" '
            f'stroke="{col}" stroke-width="3.5"/>'
            f'<circle cx="{bx:.0f}" cy="{by:.0f}" r="27" fill="{col}" '
            f'stroke="#111" stroke-width="3"/>'
            f'<text x="{bx:.0f}" y="{by + 11:.0f}" text-anchor="middle" '
            f'font-size="32" font-weight="700" fill="#111" '
            f'font-family="sans-serif">{step}</text>')
    for s, net, x, y, r in DASHED:
        if s != side:
            continue
        px, py = fwd(side, x, y)
        parts.append(
            f'<circle cx="{px:.0f}" cy="{py:.0f}" r="{r}" fill="none" '
            f'stroke="{COLORS[net]}" stroke-width="3.5" '
            f'stroke-dasharray="10 8" opacity=".9"/>')
    for s, text, x, y, dx, dy, anchor in CONTEXT:
        if s != side:
            continue
        px, py = fwd(side, x, y)
        tx, ty = px + dx, py + dy
        halo = (f'<text x="{tx:.0f}" y="{ty:.0f}" text-anchor="{anchor}" '
                f'font-size="26" font-family="sans-serif" '
                f'stroke="#000" stroke-width="6" stroke-opacity=".6" '
                f'fill="none">{text}</text>')
        parts.append(
            halo +
            f'<text x="{tx:.0f}" y="{ty:.0f}" text-anchor="{anchor}" '
            f'font-size="26" font-family="sans-serif" '
            f'fill="#d8d8cf">{text}</text>')
    return "\n".join(parts)


# ---- closeup crops -------------------------------------------------------
# (file, side, x_mm, y_mm, half_px, ring_r_px)
CROPS = [
    ("cu_sw2.png", "bottom", 92.75, 90.6, 230, 46),   # SW2 body + pad 2
    ("cu_c16.png", "top", 107.94, 105.13, 150, 52),
    ("cu_c28.png", "bottom", 103.14, 88.38, 150, 44),
    ("cu_clip.png", "bottom", 111.6, 100.0, 210, 84),
    ("cu_c17.png", "top", 107.20, 101.83, 150, 52),
    ("cu_c19.png", "top", 91.43, 103.62, 150, 48),
    ("cu_tp1.png", "bottom", 88.9, 95.0, 165, 62),
    ("cu_l1.png", "top", 98.35, 106.3, 185, 56),
    ("cu_gnd.png", "bottom", 100.0, 100.0, 260, 120),
    ("cu_usb.png", "bottom", 98.8, 87.4, 260, 0),      # R6/R7 + J1 pads
    ("cu_j1leg.png", "top", 95.67, 85.12, 165, 60),
]
# ring drawn at the probe pad, which may be off crop-center
CROP_RING_AT = {
    "cu_sw2.png": ("bottom", 93.17, 89.95),
    "cu_c16.png": ("top", 107.94, 105.62),
    "cu_c17.png": ("top", 107.20, 102.60),
    "cu_c19.png": ("top", 91.43, 104.10),
    "cu_clip.png": ("bottom", 112.40, 100.0),
    "cu_l1.png": ("top", 98.70, 106.82),
    "cu_tp1.png": ("bottom", 88.20, 95.0),
    "cu_c28.png": ("bottom", 103.14, 88.38),
    "cu_gnd.png": ("bottom", 100.0, 100.0),
    "cu_j1leg.png": ("top", 95.67, 85.12),
}
CROP_RING_COLOR = {
    "cu_sw2.png": COLORS["PWR_EN"], "cu_c16.png": COLORS["VBUS"],
    "cu_c28.png": COLORS["VBUS"], "cu_clip.png": COLORS["VBATT"],
    "cu_c17.png": COLORS["VBATT"], "cu_c19.png": COLORS["3V3"],
    "cu_tp1.png": COLORS["RUN"], "cu_l1.png": COLORS["CORE"],
    "cu_gnd.png": COLORS["GND"], "cu_j1leg.png": COLORS["GND"],
}

BG = (26, 26, 30, 255)
srcs = {s: Image.open(SCRATCH / f"probe_{s}.png").convert("RGBA")
        for s in ("top", "bottom")}
for s in srcs:
    base = Image.new("RGBA", srcs[s].size, BG)
    base.alpha_composite(srcs[s])
    srcs[s] = base

for fname, side, x, y, half, ring in CROPS:
    cx, cy = fwd(side, x, y)
    box = (int(cx - half), int(cy - half), int(cx + half), int(cy + half))
    crop = srcs[side].crop(box).resize((half * 4, half * 4), Image.LANCZOS)
    d = ImageDraw.Draw(crop)
    if fname in CROP_RING_AT:
        rs, rx, ry = CROP_RING_AT[fname]
        rpx, rpy = fwd(rs, rx, ry)
        # position within the upscaled crop
        ux, uy = (rpx - box[0]) * 2, (rpy - box[1]) * 2
        rr = ring * 2
        col = CROP_RING_COLOR[fname]
        for w, c in ((13, "#000000"), (7, col)):
            d.ellipse([ux - rr, uy - rr, ux + rr, uy + rr],
                      outline=c, width=w)
    crop = crop.resize((half * 2, half * 2), Image.LANCZOS)
    crop.convert("RGB").save(OUT / fname, quality=92)
    print("wrote", fname)

shutil.copy(SCRATCH / "probe_top.png", OUT / "board_front.png")
shutil.copy(SCRATCH / "probe_bottom.png", OUT / "board_back.png")

# ---- page ----------------------------------------------------------------
ov_top = svg_markers("top")
ov_bot = svg_markers("bottom")

C = COLORS


def chip(net, label=None):
    return (f'<span class="chip" style="--c:{C[net]}">'
            f'{html.escape(label or net)}</span>')


page = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>simple_earring — USB bring-up probe map</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ background:#1a1a1e; color:#ddd; font-family:sans-serif;
         margin:1.2rem auto; max-width:1500px; padding:0 1rem; }}
  h1 {{ font-size:1.25rem; font-weight:600; }}
  h2 {{ font-size:1.05rem; font-weight:600; color:#ccc; margin:2rem 0 .6rem; }}
  a {{ color:#8bf; }}
  p, li {{ line-height:1.5; max-width:72rem; }}
  .chip {{ display:inline-block; padding:.05rem .45rem; border-radius:99px;
          background:color-mix(in srgb, var(--c) 18%, transparent);
          border:1px solid var(--c); color:var(--c);
          font-size:.82em; font-weight:600; white-space:nowrap; }}
  .note {{ background:#26262e; border-left:4px solid #ffb02e;
          border-radius:6px; padding:.7rem 1rem; margin:.8rem 0; }}
  .note.blue {{ border-left-color:#6b9bff; }}
  .note.green {{ border-left-color:#4ade80; }}
  .boards {{ display:flex; flex-wrap:wrap; gap:1.4rem; margin-top:.8rem; }}
  .stage {{ flex:1 1 460px; max-width:700px; margin:0; }}
  .stage .wrap {{ position:relative; }}
  .stage img {{ display:block; width:100%; height:auto; border-radius:10px; }}
  .stage svg {{ position:absolute; inset:0; width:100%; height:100%; }}
  .stage figcaption {{ text-align:center; color:#aaa; padding:.4rem;
                       font-size:.9rem; }}
  table {{ border-collapse:collapse; margin:.8rem 0; font-size:.92rem; }}
  th, td {{ border:1px solid #3a3a42; padding:.5rem .7rem; text-align:left;
           vertical-align:top; }}
  th {{ background:#26262e; color:#ccc; }}
  td.badge {{ text-align:center; font-weight:700; font-size:1.05rem; }}
  .cards {{ display:grid; gap:1rem;
           grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); }}
  .card {{ background:#222228; border:1px solid #34343c; border-radius:10px;
          overflow:hidden; }}
  .card img {{ width:100%; display:block; }}
  .card .cap {{ padding:.55rem .8rem; }}
  .card .cap b {{ font-size:.95rem; }}
  .card .val {{ font-family:ui-monospace, monospace; font-size:1.25rem;
               margin-top:.15rem; }}
  .card .why {{ color:#999; font-size:.8rem; margin-top:.3rem;
               line-height:1.35; }}
  .flow {{ overflow-x:auto; }}
  kbd {{ background:#333; border-radius:4px; padding:.05rem .35rem;
        font-size:.85em; }}
</style></head><body>

<h1>USB bring-up — where to put the meter
  <span style="color:#888;font-weight:400;font-size:.85rem">
  &nbsp;ordered rev <code>43eadc1</code> (the board in your hand)
  &nbsp;·&nbsp; <a href="../index.html" style="font-size:.9rem">back to dashboard</a></span></h1>

<p>Symptom: plugged into USB, nothing in <code>dmesg</code> at all — the host
never saw a D+ pull-up, so the RP2354A boot ROM never reached USB. Power flows
{chip("VBUS")} → charger → {chip("VBATT")} → LDO → {chip("3V3")} → RP2354A
(which makes its own {chip("CORE", "1.1 V core")} with the internal switcher).
The LDO enable is gated by the back-side slide switch
{chip("PWR_EN", "SW2")} — the whole board is dead when it's off, USB or not.
Work the numbered steps in order; the first missing rail is the culprit.</p>

<div class="flow">
<svg width="1120" height="120" viewBox="0 0 1120 120" font-family="sans-serif" font-size="15">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5"
    markerWidth="7" markerHeight="7" orient="auto">
    <path d="M0 0 L10 5 L0 10 z" fill="#888"/></marker></defs>
  <g text-anchor="middle">
    <rect x="8" y="34" width="96" height="42" rx="8" fill="none" stroke="#888"/>
    <text x="56" y="60" fill="#ddd">USB-C J1</text>
    <rect x="200" y="34" width="130" height="42" rx="8" fill="none" stroke="#888"/>
    <text x="265" y="53" fill="#ddd">charger U2</text>
    <text x="265" y="70" fill="#888" font-size="12">LGS4056H</text>
    <rect x="440" y="34" width="120" height="42" rx="8" fill="none" stroke="#888"/>
    <text x="500" y="53" fill="#ddd">LDO U3</text>
    <text x="500" y="70" fill="#888" font-size="12">NCP730 3.3</text>
    <rect x="660" y="34" width="130" height="42" rx="8" fill="none" stroke="#888"/>
    <text x="725" y="53" fill="#ddd">RP2354A U1</text>
    <text x="725" y="70" fill="#888" font-size="12">boot ROM → USB</text>
    <rect x="890" y="34" width="180" height="42" rx="8" fill="none" stroke="#888"/>
    <text x="980" y="53" fill="#ddd">internal switcher</text>
    <text x="980" y="70" fill="#888" font-size="12">L1 + C12</text>
    <line x1="104" y1="55" x2="196" y2="55" stroke="#888" stroke-width="2" marker-end="url(#arr)"/>
    <text x="150" y="47" fill="{C['VBUS']}" font-weight="600">VBUS 5V ①</text>
    <line x1="330" y1="55" x2="436" y2="55" stroke="#888" stroke-width="2" marker-end="url(#arr)"/>
    <text x="383" y="47" fill="{C['VBATT']}" font-weight="600">VBATT ②</text>
    <line x1="560" y1="55" x2="656" y2="55" stroke="#888" stroke-width="2" marker-end="url(#arr)"/>
    <text x="608" y="47" fill="{C['3V3']}" font-weight="600">3V3 ④</text>
    <line x1="790" y1="55" x2="886" y2="55" stroke="#888" stroke-width="2" marker-end="url(#arr)"/>
    <text x="838" y="47" fill="{C['CORE']}" font-weight="600">1.1 V ⑥</text>
    <line x1="383" y1="100" x2="383" y2="80" stroke="#888" stroke-width="2"/>
    <text x="383" y="116" fill="{C['VBATT']}" font-size="13">LIR2032 pads (cell optional)</text>
    <line x1="500" y1="100" x2="500" y2="80" stroke="{C['PWR_EN']}" stroke-width="2" marker-end="url(#arr)"/>
    <text x="510" y="116" fill="{C['PWR_EN']}" font-size="13" text-anchor="start">EN ← SW2 slide switch ③</text>
  </g>
</svg>
</div>

<div class="note green"><b>✅ Resolved (Aug 25):</b> with a charged LIR2032
fitted the board is fully alive — USB CDC, IMU (clean 1&nbsp;g vector),
charger status and the 45-LED chain all pass. Two contributing faults:
the no-battery charger motorboat below (still true), and poor cell −
contact — the 8&nbsp;mm center pad sits below the surrounding
mask-over-traces, fixed by tinning the pad proud. This page stays as the
bench reference; test firmware lives in <code>firmware/</code>.</div>

<div class="note"><b>Before probing anything:</b> slide
{chip("PWR_EN", "SW2")} (back side, upper area near the IMU) to its other
position and replug. Its as-shipped position is undefined and it gates the
LDO — this alone would explain a completely dead board. Expected ON is knob
toward the battery (pin&nbsp;1 end); if in doubt, check step&nbsp;③ in both
positions. And use a known-good <em>data</em> cable — a charge-only lead
shows these exact symptoms.</div>

<div class="note blue"><b>No battery — sequencing matters
(finding, Aug&nbsp;24):</b> with SW2 already ON when USB is plugged, PWR_EN/VBATT
was seen motorboating ≈1.8–2.2&nbsp;V. Below ≈2.9&nbsp;V the charger trickle-limits
to ≈4&nbsp;mA (a tenth of the 41&nbsp;mA program), so the LDO + MCU waking at
≈2&nbsp;V overload it and VBATT collapses and retries — a "wave" on a DMM.
<b>Cold-start recipe: SW2 OFF → plug USB → wait for VBATT ≈4.2&nbsp;V →
SW2 ON</b> (full 41&nbsp;mA is then available; boot ROM needs ≈15–25&nbsp;mA).
If it still sags, fit a <em>charged</em> cell or a ≈4&nbsp;V supply: side clip
lands = +, center pad = −. A discharged LIR2032 clamps VBATT low — remove it.
Powered-off resistance sanity check: {chip("3V3")}→GND and
{chip("VBATT")}→GND should each read tens of kΩ or more, not single-digit
ohms.</div>

<h2>Probe map — black lead on {chip("GND", "G")}, work ① → ⑥</h2>
<div class="boards">
  <figure class="stage">
    <div class="wrap">
      <img src="board_back.png" alt="back of board, annotated">
      <svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{ov_bot}</svg>
    </div>
    <figcaption>BACK — battery side, as you look at it (USB tip up).
    Big center pad = GND: clip the black lead here.</figcaption>
  </figure>
  <figure class="stage">
    <div class="wrap">
      <img src="board_front.png" alt="front of board, annotated">
      <svg viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{ov_top}</svg>
    </div>
    <figcaption>FRONT — LED side (USB tip up). G = USB shell leg barrel,
    an easy front-side ground.</figcaption>
  </figure>
</div>

<h2>The ladder</h2>
<table>
<tr><th></th><th>net</th><th>probe at</th><th>expect</th>
    <th>if it's missing / wrong</th></tr>
<tr><td class="badge" style="color:{C['GND']}">G</td><td>{chip("GND")}</td>
  <td>back: BT1 center pad (8 mm disc) · front: USB shell-leg barrel</td>
  <td>reference</td><td>—</td></tr>
<tr><td class="badge" style="color:{C['VBUS']}">1</td><td>{chip("VBUS")}</td>
  <td>front: C16 pad ① · back: C28 pad ①</td>
  <td>5.0 V</td>
  <td>cable / port / USB-C solder. Try the other plug orientation and an
  A-to-C cable; inspect J1's pads at the tip.</td></tr>
<tr><td class="badge" style="color:{C['VBATT']}">2</td><td>{chip("VBATT")}</td>
  <td>back: either bare clip land ② · front: C17 pad ②</td>
  <td>≈4.2 V (may wander 4.05–4.2 with no cell)</td>
  <td>charger U2 (DFN2×2, front right — check solder), or VBATT shorted.
  0 V here with VBUS good = charger problem.</td></tr>
<tr><td class="badge" style="color:{C['PWR_EN']}">3</td><td>{chip("PWR_EN")}</td>
  <td>back: SW2 middle pad ③</td>
  <td>≈VBATT when ON, 0 V when OFF</td>
  <td>stuck low in both positions → switch solder / wrong part.</td></tr>
<tr><td class="badge" style="color:{C['3V3']}">4</td><td>{chip("3V3")}</td>
  <td>front: C19 pad ④ (next to LDO)</td>
  <td>3.30 V</td>
  <td>VBATT + PWR_EN good but no 3V3 → LDO U3 solder, or 3V3 rail
  shorted (recheck Ω).</td></tr>
<tr><td class="badge" style="color:{C['RUN']}">5</td><td>{chip("RUN")}</td>
  <td>back: TP1, the lone gold square ⑤</td>
  <td>3.3 V</td>
  <td>held low → R2 pull-up or a short on RUN; chip is in reset.</td></tr>
<tr><td class="badge" style="color:{C['CORE']}">6</td><td>{chip("CORE", "1.1 V core")}</td>
  <td>front: L1 pad ⑥ (bare inductor land, below-left of the MCU)</td>
  <td>1.1 V</td>
  <td>3V3 good but no 1.1 V → internal switcher: inspect L1 (the part JLC
  flagged) and C12 solder.</td></tr>
<tr><td class="badge" style="color:{C['DATA']}">7</td><td>{chip("DATA", "USB D±")}</td>
  <td>back: beep J1's center pads (dashed ring) ↔ R6/R7 ⑦; then R6/R7 far
  side ↔ onward (27 Ω in series)</td>
  <td>≈0 Ω to the near side, ≈27 Ω through</td>
  <td>only matters if ①–⑥ all pass: open joint on the fine USB pads or the
  ESD chip U5.</td></tr>
</table>

<p>If every rail is good and it still won't enumerate: hold
<kbd>BOOTSEL</kbd> (front button) while plugging in, and eyeball the 12 MHz
crystal's solder (front, above the MCU) — the boot ROM needs the crystal
running before USB works. Blank internal flash should drop into the USB
bootloader on its own (<code>2e8a:000f RP2350 Boot</code> in
<code>lsusb</code>).</p>

<h2>Closeups</h2>
<div class="cards">
  <div class="card" style="border-color:{C['GND']}">
    <img src="cu_gnd.png"><div class="cap"><b>G — black lead here</b>
    <div class="val" style="color:{C['GND']}">GND</div>
    <div class="why">Back center: the 8 mm battery − pad. Solid ground for
    every measurement.</div></div></div>
  <div class="card" style="border-color:{C['GND']}">
    <img src="cu_j1leg.png"><div class="cap"><b>G — front-side ground</b>
    <div class="val" style="color:{C['GND']}">GND</div>
    <div class="why">USB shell leg barrel (gold oval) — handy when probing
    the front without flipping the board.</div></div></div>
  <div class="card" style="border-color:{C['VBUS']}">
    <img src="cu_c16.png"><div class="cap"><b>① C16 — VBUS bulk cap (front)</b>
    <div class="val" style="color:{C['VBUS']}">5.0 V</div>
    <div class="why">Ringed pad = VBUS end. Near the charger, front right
    edge.</div></div></div>
  <div class="card" style="border-color:{C['VBUS']}">
    <img src="cu_c28.png"><div class="cap"><b>① C28 — VBUS at the ESD chip (back)</b>
    <div class="val" style="color:{C['VBUS']}">5.0 V</div>
    <div class="why">Same net, back side, right below the USB connector —
    saves flipping.</div></div></div>
  <div class="card" style="border-color:{C['VBATT']}">
    <img src="cu_clip.png"><div class="cap"><b>② battery clip land (back)</b>
    <div class="val" style="color:{C['VBATT']}">≈4.2 V</div>
    <div class="why">Either bare side land (the clip isn't fitted on this
    rev). Fed by the charger even with no cell.</div></div></div>
  <div class="card" style="border-color:{C['VBATT']}">
    <img src="cu_c17.png"><div class="cap"><b>② C17 — VBATT cap (front)</b>
    <div class="val" style="color:{C['VBATT']}">≈4.2 V</div>
    <div class="why">Ringed pad = VBATT end, right next to the charger's BAT
    pin.</div></div></div>
  <div class="card" style="border-color:{C['PWR_EN']}">
    <img src="cu_sw2.png"><div class="cap"><b>③ SW2 middle pad — PWR_EN (back)</b>
    <div class="val" style="color:{C['PWR_EN']}">≈VBATT on · 0 V off</div>
    <div class="why">The LDO enable. Check in both switch positions — this is
    the prime suspect for a totally dead board.</div></div></div>
  <div class="card" style="border-color:{C['3V3']}">
    <img src="cu_c19.png"><div class="cap"><b>④ C19 — 3V3 at the LDO (front)</b>
    <div class="val" style="color:{C['3V3']}">3.30 V</div>
    <div class="why">Ringed pad = 3V3 end (the pad nearer the LDO's OUT
    pin).</div></div></div>
  <div class="card" style="border-color:{C['RUN']}">
    <img src="cu_tp1.png"><div class="cap"><b>⑤ TP1 — RUN (back)</b>
    <div class="val" style="color:{C['RUN']}">3.3 V</div>
    <div class="why">The lone gold square near the back right edge (the pair
    further down is SWD).</div></div></div>
  <div class="card" style="border-color:{C['CORE']}">
    <img src="cu_l1.png"><div class="cap"><b>⑥ L1 — 1.1 V core (front)</b>
    <div class="val" style="color:{C['CORE']}">1.1 V</div>
    <div class="why">Ringed pad = switcher output side of the inductor. No
    1.1 V with good 3V3 = the JLC-flagged part.</div></div></div>
  <div class="card" style="border-color:{C['DATA']}">
    <img src="cu_usb.png"><div class="cap"><b>⑦ USB data path (back)</b>
    <div class="val" style="color:{C['DATA']}">≈0 Ω / 27 Ω</div>
    <div class="why">J1 fine pads → ESD chip → R6/R7 (the 27 Ω pair).
    Continuity only; board unplugged.</div></div></div>
</div>

<p style="color:#777;font-size:.85rem;margin-top:2rem">Generated from the
ordered rev <code>43eadc1</code> board file; renders are orthographic, so
positions are exact (±0.5 mm). Marker coordinates come straight from the
netlist pads.</p>
</body></html>
"""
(OUT / "index.html").write_text(page)
print("wrote", OUT / "index.html")
