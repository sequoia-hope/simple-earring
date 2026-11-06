# LED1–LED45: XINGLIGHT XL-1615RGBC-RF common-anode RGB LED (variant C)

**Datasheet:** `design/datasheets/xl-1615rgbc-rf.pdf` (XINGLIGHT, 15 pages, undated; copied from round-pendant, LCSC
C965840). Read: pp. 1–8 and 11–13. Pages 6 (curves) and 8 (outline, pinout, land pattern) were also read as images.
**MPN:** XL-1615RGBC-RF
**Supplier:** `C965840 XL-1615RGBC-RF (XINGLIGHT, SMD-4P,1.6x1.5mm): extended, JLC stock 718328, lifecycle normal, checked 2026-11-05`
(~$0.014–0.016 each, about half the XL-1010's $0.027–0.031: ~$0.7 less per board for 45.)
**Why this part:** the user's call (2026-11-05). It's the "slightly larger LED" round-pendant's parallelogram study names
for its low-density tiers. It's also 1.6 × 1.5 mm, which puts it out of the 1 × 1 mm fine-pitch class.

**Footprint:** `library/parts.pretty/LED_XL-1615RGBC`, written from p.8's recommended pattern:
- **Pads:** 0.45 × 0.65 mm at (±0.625, ±0.475), so a 0.80 mm gap between the columns, 0.30 mm between the rows, and
  1.70 × 1.60 mm overall.
- **Pin map (top view, p.8):** 1 top-left, 2 bottom-left, 3 top-right, 4 bottom-right, with the polarity mark between 1
  and 2. This is **not the XL-1010's order.**
- **Polarity (p.8 schematic):** **pad 2 = common anode (+)**; 1 = R, 3 = G, 4 = B cathodes. This matches `circuit.py`
  RGB_LEDS["rgb_led_1615"].
- **Body:** 1.6 × 1.5 × 0.6 mm, with a 1.0 mm lens window.
- **Courtyard:** ±0.90 × ±0.85, 0.05 mm outside the copper. That's tight on purpose, for the 2.44 mm ring pitch, as the
  XL-1010's was.

## Fit on the ring (place.py)

- **Angle:** variant B set its LEDs at 45° to the ring tangent, the angle the WS2816C chain uses. At 45° the XL-1615's pad
  corners come within ~0.1 mm of the next LED's at 2.44 mm pitch, under JLC's 0.15 mm SMD gap. So variant C sets
  `leds.matrix.led_angle: 0` (square to the tangent), which leaves ~0.7 mm.
- **The tip slot:** LED1, LED2, LED33 and LED34 sit next to J1's oval shell legs (1.2 × 2.0 mm at ±4.33, −14.88 / −19.06).
  At the tangent angle their pads shorted to the legs. Snapped to the nearest 90° they fit the 2.28 mm slot between the
  legs, with ~0.34 mm each side. Placed board DRC: 0 errors.

## Absolute max vs our worst case (p.3; 9 SW × 15 CS, REXT 47 kΩ, see aw20198qnr.md)

| Parameter | Abs max | Our worst case | Margin |
|---|---|---|---|
| IF continuous | 20 mA each colour | Peak 8.5 mA, average ≤ 0.84 mA | OK: peak is under the continuous rating |
| IFP | 80 mA | 8.5 mA | OK |
| IF derating (p.6 bottom-left; y axis is mA) | 20 mA to ~27 °C, 10 mA at 85 °C | 8.5 mA peak | OK across the range |
| PD | R 50, G/B 70 mW | R 2.0 V × 0.84 = 1.7 mW; G/B 3.0 V × 0.84 = 2.5 mW | OK |
| VR | 5 V (IR ≤ 5 µA at 5 V) | ≈ VSYS = 4.95 V on USB during de-ghost blanking, µA-limited; ≤ 4.2 V on the cell | Inside, thin on USB (as B) |
| ESD | 2 kV | Front ring | Handle with ESD care |
| Operating / storage | −40 … +85 °C | On the body | OK |
| Reflow | 260 °C, 6 s abs; recommended 240 ± 5 °C / 6 s and **≤ 2 passes** (p.11); MSL 3 | JLC double-sided, 2 passes | At the limit: no third reflow, no hot-air rework of neighbours |

## Optics at our current (p.4, p.6)

At IF = 20 mA: R 100–180, G 350–800, B 120–180 mcd. VF: R 1.8–2.4, G/B 2.6–3.4 V. 120° viewing angle.

The p.6 relative-intensity curve, read at the 8.5 mA peak:
- **G and B:** ~0.6 of the 20 mA value, so G ≈ 210–480 mcd and B ≈ 72–108 mcd while lit.
- **Red: ~0.3.** The curve starts at ~5 mA, so red is weak below ~10 mA. That gives R ≈ 30–54 mcd, about 4–6 mcd per mA
  of peak. The WS2816C was 26 mcd/mA, and the XL-1010 5–10.

Consequences:
- **Dim red with PWM, never with SL or GCC.** SL and GCC lower the instantaneous current, and red falls off much faster
  than G/B as current drops.
- **Purple and red cost more current than on variant A.** Variant B's corrected battery table already assumed 1.8–2.9×.
  The XL-1615's red sits at the bottom of that range or below it, so take the upper end.
- If red is too dim on the bench, the lever is REXT (aw20198qnr.md: 39 k → 10.3 mA), traded against the cell budget.

## Open questions

- Red below 10 mA: the curve is coarse there, so measure on the bench.
- The reel's Iv/VF bins (p.5 codes D2–E7, N11–N13).
- Independent review: `design/gates/phase1-variant-c-review.md`, PASS WITH FIXES (2026-11-05). m6 (reflow) is folded in.
