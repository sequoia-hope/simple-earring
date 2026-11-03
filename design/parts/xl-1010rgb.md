# LED1–LED45: XINGLIGHT XL-1010RGB-YG common-anode RGB LED (variant B)

**Datasheet:** `design/datasheets/xl-1010rgb-yg.pdf` (XINGLIGHT, 15 pages, undated; copied from round-pendant, LCSC
C965834). Read: all 15 pages. Pages 6 (curves) and 8 (outline, pinout, land pattern) were also read as images.
**MPN:** XL-1010RGB-YG
**Supplier:** `C965834 XL-1010RGB-YG (XINGLIGHT, SMD-4P,1x1mm): extended, JLC stock 12478, lifecycle normal, checked 2026-11-03`
(45 per board: 12,478 covers ~270 boards.)
**Footprint:** `library/parts.pretty/LED_XL-1010RGB`, checked against p.8 and correct as copied (unchanged):
- **Pads:** 0.45 × 0.45 mm at (±0.40, ±0.40), giving the drawing's 0.35 mm gaps both ways and 1.25 mm overall.
- **Pin map (top view):** 1 top-left, 2 top-right, 3 bottom-left, 4 bottom-right, as p.8's top view draws them. The
  bottom view is the same pattern flipped about the horizontal axis (3, 4 on top; 1, 2 below), which is consistent.
- **Fab pin-1 chamfer** at pad 1.
- **Package pads** (bottom view) are 0.32 mm at 0.335 mm offset. The land overhangs them 0.13 mm outward, and the inner
  edges coincide.
- **Courtyard** ±0.65 mm, only 0.025 mm outside the copper. That is deliberately tight for the 2.44 mm ring pitch.
- **Polarity:** pad 3 = common anode (+); 1 = R, 2 = G, 4 = B cathodes (p.8 schematic). This matches
  `scripts/circuit.py` RGB_PIN.

## Absolute max vs our worst case (p.3; 9 SW × 15 CS, RISET 47 kΩ, see is31fl3741a.md)

| Parameter | Abs max | Our worst case | Margin |
|---|---|---|---|
| IF continuous | 20 mA each colour | Average ≤ 0.80 mA (0.86 at +8 %); peak 8.1 mA (8.7) | OK, peak is below even the continuous rating |
| IFP (pulse ≤ 0.1 ms, duty ≤ 1/10) | R 60, G/B 80 mA | 32 µs pulses at 1/10.125 duty, 8.7 mA | OK, not needed |
| IF derating (p.6, bottom-left curve, mislabelled "relative luminous intensity"; y axis is mA) | 20 mA to ~25 °C, falling to 10 mA at 85 °C | 0.86 mA | OK |
| PD | R 50, G/B 70 mW | R 1.95 V × 0.86 = 1.7 mW; G/B 2.75 × 0.86 = 2.4 mW (≤ 2.9 mW at top-bin Vf) | OK |
| VR | 5 V (also the IR ≤ 1 µA test condition, p.4) | ≈ VSYS = 4.95 V during the driver's 2 µs de-ghost blanking each slot, current-limited to ≤ 77 µA by the 32 kΩ pulls (is31fl3741a.md); ≤ 4.2 V on battery | Inside, thin on USB |
| ESD | 2 kV (HBM implied) | Front ring, behind no window; handle with ESD care | note |
| Operating temp | −30 … +85 °C | On the body | OK |
| Reflow | 260 °C ≤ 6 s (p.3); profile 255 °C peak (p.7); recommended 240 ± 5 °C / 6 s (p.11); **≤ 2 reflows** | JLC double-sided: 2 passes | At the limit: no third reflow, no hot-air rework of neighbours |
| MSL | 3: 168 h floor life after opening, bake 60 °C 24 h (p.13) | JLC handles | note |

## Calculations

### Electro-optical data used (p.4–p.6)

- **Iv at 20 mA:** R 100–200, G 550–1000, B 80–200 mcd → R 5–10, G 27.5–50, B 4–10 mcd/mA.
  - The bins are D2–D5 and E5–E9 (p.5); the reel bin is not selectable at JLC.
- **Vf at 20 mA:** R 1.8–2.4 V, G/B 2.6–3.4 V (bins N11-4 … N13-5, ±0.1 V).
- **From the p.6 V-I curve at our 8.1 mA:** R ≈ 1.95 V, G/B ≈ 2.75 V typical; top bin ≈ 3.25 V.
- **Relative intensity against current (p.6):** G/B ≈ 0.35–0.4 of the 20 mA value at 5 mA and ~0.55 at 8 mA. Per mA
  that is ~1.4× the 20 mA efficiency.
  - **Red is drawn crossing zero at ~5 mA**, which would mean no light below 5 mA. That is a drawing artefact: AlGaInP
    emits at µA currents. But the curve gives no usable red efficiency below ~10 mA (~0.9× at 10 mA).
  - The budget below therefore uses the 20 mA per-mA figures for all three colours.

### Luminance match to the current board (WS2816C, 90 / 190 / 25 mcd at ~3.5 mA per channel)

| | WS2816C mcd/mA | XL-1010 mcd/mA (bin min–max) | XL current for the same light |
|---|---|---|---|
| R | 26 | 5–10 | 2.6–5.1 × |
| G | 54 | 27.5–50 | 1.1–2.0 × |
| B | 7.1 | 4–10 | 0.7–1.8 × |

The firmware's purple (R 4, B 8 counts at the brightest) costs **0.30 mA per LED typical, 0.48 mA lowest bin**, against
0.165 mA on the WS2816C: **1.8–2.9× the LED current for the same look.** Red dominates. That is why the battery figures
in variant-b-matrix.md are corrected (its LED term was taken as equal on both boards).

### Colour balance

- **Spread between colours.** Green gives ~5× red's and blue's light per mA. On top of that, the bins spread ±50 % (R
  100–200, B 80–200).
- **Handling.** Per-LED Scaling registers set the white point: SL_G ≈ 50 against SL_R ≈ SL_B ≈ 255 for equal mcd.
  PWM is then left to carry the animation.
- **A whole-reel bin shift** is one constant per colour in firmware, measured on the first board.

## Fine print

- The top-view and bottom-view drawings mirror each other. Check pin 1 at the CPL step (JLC's preview of the first
  part), because the body has no top-side mark: all four corners carry the same green mark in the top view (p.8). The
  bottom-view triangle sits between pads 3 and 4.
- Tolerance ±0.25 mm unless noted (p.8).
- "Resistors for protection should be applied" (p.14) is for constant-voltage drive. The driver's CS sinks regulate
  the current (Circuit A), so no series resistors.
- Hand soldering: < 30 W iron, < 300 °C, < 3 s, once per terminal (p.11). Rework is risky on 1 mm parts.
- No pressure on the lens while hot. Clean with alcohol only (p.12, p.15).

## Layout

- 45 parts on the ring at ~2.44 mm pitch, one orientation per arc.
- Anode (pad 3) to its arc's SW net. R/G/B cathodes to that LED's CS triplet on the ring bus (is31fl3741a.md: 9 arcs of 5).
- G (pad 2) exits through the 0.35 mm centre gap; R and B (pads 1 and 4) go down the sides.

## Open questions

1. Red efficiency below 10 mA: the p.6 curve is unusable there. Measure one LED at 1–8 mA at bring-up, before the
   firmware colour tables are fixed.
2. Reel Iv/Vf bins are unknown until delivery. They set the firmware white point and the top-bin headroom case.
