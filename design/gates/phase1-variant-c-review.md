# Phase 1 review — variant C parts (AW20198QNR, XL-1615RGBC-RF)

Independent datasheet review, 2026-11-05. Read-only check of `design/parts/aw20198qnr.md` and
`design/parts/xl-1615rgbc.md` against `design/datasheets/aw20198qnr.pdf` (Awinic V1.3) and
`design/datasheets/xl-1615rgbc-rf.pdf`, plus `scripts/circuit.py` (AW_SW_PIN / AW_CS_PIN / RGB_LEDS /
add_matrix), `design.c.yaml` and the two footprints. Pages 2, 37, 38 (AW) and 6, 8 (XL) were rendered and
read as images. Every number below was recomputed from the datasheet, not copied from the audit.

## What checks out (no finding)

| Item | Datasheet | Result |
|---|---|---|
| AW pin table, all 41 pins | p.2 Fig. 2, p.3 table | 1–4 SW8/6/4/2, 5 PVCC, 6–11 SW1/3/5/7/9/11, 12–15 CS18–15, 16 PGND, 17–21 CS14–10, 22 VCC, 23 GND, 24 AD1, 25 AD0, 26 EN, 27 SCL, 28 SDA, 29 ISET, 30 SYNC, 31–39 CS9–1, 40 SW10, 41 GND/EP. `AW_SW_PIN`, `AW_CS_PIN` and the fixed pins in `add_matrix()` match exactly |
| I²C address | p.11 table | AD0 = GND, AD1 = GND → 0x20. Netlist ties 24 and 25 to GND. Correct |
| SWSEL for 9 lines | p.25 GCR | `1000: SW1~SW9 active SW10~SW11 not active`. Correct; SW10/SW11 (pins 40, 11) NC is fine. Default is 1011 (all 11), firmware must write it |
| Imax | p.18, p.35 eq. (1) | K = 400 V; 400 / 47 k = **8.51 mA**. Correct |
| Duty | p.7–8, p.18 | TSETUP 0.25 + 5 × TDLY 0.125 + TPWM 16 + THOLD 0.125 + TDG 1 = 18.0 µs per slot; numerator 15.9375 µs. 15.9375 / 18.0 / 9 = **0.0984**; the datasheet's own 11-SW case gives 0.0805, and TSCAN 198 µs at SWSEL 1011 = 11 × 18 confirms the period scales with N. Correct |
| Average per die, full white | — | 8.51 × 0.0984 = **0.837 mA**; 135 × 0.837 = **113 mA**; + 1.8 mA IACT + ~15 mA system = **~130 mA**, under the 140 mA cell rating. Correct |
| Per-SW peak | p.7 | 15 × 8.51 = **128 mA**, vs 720 mA switch rating (= 18 × 40 mA at 10 k). Correct |
| Driver dissipation at 4.95 V | p.6 | 0.837 mA × (45 × 3.0 + 90 × 2.2) = 0.837 × 333 = **279 mW** + 9 mW quiescent; × 33 °C/W = **+9.5 °C** (JEDEC board). Correct; the "+20 °C on a small board" allowance is sensible |
| Abs max table | p.6 | VCC/PVCC 6 V, inputs −0.3…VCC, SW −0.3…PVCC, CS −0.3…VCC, ISET 2 V, TJ 160 °C, θJA 33 °C/W, TSD 165 °C, MSL 3 (p.6 ordering table). All as the audit states |
| Standby / active current | p.7 | ISTB 1.3 µA (EN = 0 or CHIPEN = 0); IACT 1.8 mA all LEDs off. Correct |
| EN internal pull-down | p.3 | "internally pulled down to GND with a resistor of 1 MΩ" — dropping the IS31's external R36 is justified. SYNC has the same 1 MΩ, so NC is fine (Figure 1 also leaves it open) |
| I²C pull-ups | p.11 | "4.7 kΩ is recommended for 400 kHz, 1 kΩ for 1 MHz"; bus 1.8–3.3 V allowed. R38/R39 4.7 k to 3V3 correct for 400 kHz |
| Logic thresholds | p.7 | LGC = 0: VIH 1.4 V / VIL 0.4 V; LGC = 1: 2.4 / 0.6 V. 3.3 V GPIO fine either way |
| Decoupling | p.2 Fig. 1, p.35 | 1 µ + 0.1 µ at PVCC (C1/C2) and at VCC (C3/C4), REXT close to the chip. C80–C83 + C86 bulk cover it |
| MCU pins | RP2350 GPIO function table (F3 = I²C: even GPIO = SDA, odd = SCL) | GPIO16 = I2C0 SDA, GPIO17 = I2C0 SCL — confirmed from the RP2350 function table. GPIO18 for EN is any-function. QFN-60 pins 27/28/29 as `GPIO{}` maps them |
| QFN-40 footprint | p.37–38 | 40 × 0.50 × 0.20 at 0.40 pitch, centres ±2.35 (5.20 span), inner edge 2.10; EP 3.40 → 0.40 mm pad-to-EP gap; 10 pads per side spanning 3.80 edge-to-edge. Pin 1 top-left, 1–10 down the west side, 11–20 west→east along the south, 21–30 up the east, 31–40 east→west along the north — matches Fig. 2 (top view) and the p.38 land pattern (the p.37 bottom view is flipped top-to-bottom, consistent). Paste 4 × 1.3² / 3.4² = 58 %. Correct |
| LED footprint | p.8 | Pads 0.45 × 0.65; column centres ±0.625 (the "1.25" dimension), row centres ±0.475 (0.3 gap), 1.70 × 1.60 overall. Top view: 1 TL, 2 BL, 3 TR, 4 BR, polarity mark on the left edge between 1 and 2. Schematic: **2 = common anode (+), 1 R, 3 G, 4 B**. Footprint and `RGB_LEDS["rgb_led_1615"]` match |
| LED abs max | p.3 | IF 20 mA, IFP 80 mA, PD R 50 / G,B 70 mW, VR 5 V (IR ≤ 5 µA), ESD 2 kV, −40…85 °C, reflow 260 °C 6 s, MSL 3. As the audit states |
| LED optics | p.4, p.6 | Iv at 20 mA R 100–180, G 350–800, B 120–180 mcd; VF R 1.8–2.4, G/B 2.6–3.4 V. p.6 relative-intensity curve at 8.5 mA: G/B ≈ 0.6, R ≈ 0.25–0.35 (curve leaves zero at ~5 mA). Audit's reading is fair. V-I curve: R ≈ 1.9 V, G/B ≈ 2.7–2.8 V at 8.5 mA |
| IF derating | p.6 bottom-left | 20 mA flat to ~27 °C, linear to 10 mA at 85 °C. 8.5 mA peak is under the curve everywhere |
| Matrix map | `led_matrix()` with `bus: sw` | 45 LEDs → SW = (i mod 9) + 1, CS = 3·(i div 9) + {1,2,3} → SW1–9, CS1–15; `used_cs` = 15. Consistent with `per_sw: 5` and the audit |

## Findings (ranked)

### MAJOR — none

### MINOR

**m1. Headroom floor is optimistic: sink/switch headroom does not scale linearly to zero** (AW p.7, p.16).
Audit: VHR scaled proportionally to 0.07 V (CS) + 0.13 V (SW), floor ≈ 2.95 V for G/B.
Datasheet: VHR_CS is only specified at 40 mA (300 mV) and VHR_SW at 720 mA (750 mV); a current sink's compliance has a
fixed component, and the open-detect threshold VTHOPEN = 0.1 V (p.16) means the part itself treats < 0.1 V on a CS pin as
"open". Use ≥ 0.15 V for CS and ~0.13 V for SW. With VF(G/B) ≈ 2.75 V typ at 8.5 mA the floor is ≈ 3.05 V typ; for the
top VF bin (N13-4, 3.0–3.2 V at 20 mA → ~2.95–3.1 V at 8.5 mA) it is ≈ 3.25–3.4 V. On the cell, G/B of top-bin parts start
dimming (and the colour shifts red) below ~3.3–3.4 V, not just "at the very end of discharge".
Fix: correct the numbers in `aw20198qnr.md`; set the firmware low-battery floor / colour-compensation point at ≥ 3.3 V
(or accept a red tint on the last ~10 % of the cell). Hardware stays as is.

**m2. DGCR ranges misquoted** (AW p.26).
Audit: "SW pull-downs and CS pull-ups (DGCR, 0.5–32 kΩ selectable)".
Datasheet: CSPUR (CS pull-up) 0.5–32 kΩ; SWPDR (SW pull-down) 0.25–16 kΩ; defaults 100/100 = 4 kΩ pull-up, 2 kΩ pull-down.
Fix: doc correction.

**m3. LED reverse-bias margin during de-ghost is 0.05 V on paper** (AW p.20–21, p.26; XL p.3).
Audit: ≈ VSYS reverse on unlit LEDs, 4.95 V vs VR 5 V, "inside but thin". Confirmed: with PUMD = 0 the CS pull-up (4 kΩ
default) acts for the whole time the CS is off and the SW pull-down holds the anode at ~0 V, so an unlit LED on an idle
SW sees VCC − (IR × 6 kΩ) ≈ VSYS. The 4.95 V figure assumes a 5.25 V port minus only 0.3 V in D3; D3 is actually the
silicon 1N4007WS (circuit.py), which drops ≥ 0.5 V even at mA-level load, so real-world VSYS on USB is ≈ 4.4–4.75 V and
the margin is better than the audit says. Still worth closing in firmware since it is free.
Fix: firmware sets CSPUR = 000 (CS pull-up off) and relies on SWPDR alone (the SW line's charge is what ghosts), or picks
the largest CSPUR that kills ghosting; note it in the audit. No hardware change.

**m4. VSYS bulk is derated and the slot pulses are large** (AW p.18; parts.yaml C86 = 10 µF 0603).
Audit lists C86 10 µF "extra, as B". Each 18 µs slot pulls up to 128 mA for 16 µs; the cell (IR ~0.5–0.7 Ω + Q2 0.21 Ω)
supplies it with ~0.1 V droop, and on USB the 1N4007WS's dynamic resistance adds. A 10 µF 0603 X5R at 4 V bias is ~4–6 µF
(this project's own m1 note in `phase1.md`), so the local reservoir is ~6 µF: ΔV ≈ 115 mA × 16 µs / 6 µF ≈ 0.3 V if the loop
inductance to the cell is appreciable. That droop lands on the LDO input at exactly the low-cell point where m1 bites.
Fix: C86 → 22 µF 0805 (or 2 × 10 µF) if there is room, or at least keep C86 and the PVCC 1 µF within a few mm of pin 5
and the GND return short (gate 7). Not a blocker.

**m5. Audible MLCC noise is plausible on an earring** (AW p.18 "recommended to use the PWM frequency higher than 20 kHz").
PWM is 62.5 kHz (PWMFRQ = 000) but the scan frame is 9 × 18 = 162 µs = **6.2 kHz**; any pattern that is not uniform across
the nine SW slots puts a 6.2 kHz current envelope through C86/C80, right beside the ear. Not covered by either audit.
Fix: firmware enables spread spectrum (SSCR) and slew-rate control (SRCR); prefer the 0805 bulk in m4 (less piezo
coupling than 0603); listen for it at bring-up.

**m6. LED reflow: recommended max is 240 ± 5 °C / 6 s, two passes max** (XL p.11).
Audit quotes only the 260 °C / 6 s absolute rating. p.11 also says "the recommended maximum welding temperature for the
product is 240 ± 5 °C / 6 s" and "reflow soldering should not be done more than two times"; the lead-free profile is
255 +0/−5 °C peak. JLC's double-sided job puts the LED side through two passes, at the limit, and JLC's standard lead-free
peak is above 240 °C.
Fix: record it; order the front (LED) side as the second pass if JLC lets you choose, and keep MSL-3 handling (bake if the
reel is open > 168 h, p.13).

### NOTE

**n1. Power-up sequencing** (AW p.10, Fig. 8): after POR (VCC > 2.0 V) the part needs ~2 ms to load OTP, and after
EN && CHIPEN the oscillator needs 100 µs; after a software reset (0xAE → RSTN) wait ≥ 2 ms before any I²C. Firmware.

**n2. UVLO and OT clear CHIPEN** (AW p.14–15): UVLO at 2.5 V typ and OTP at 165 °C clear GCR.CHIPEN and drop to standby;
the firmware must re-write CHIPEN = 1 after the event (read UVCR.UVFLG / OTCR.OTFLG). A 128 mA pulse on a 3.0 V cell
through ~1 Ω stays above 2.5 V, so it should not trigger in normal use.

**n3. Logic level**: with 3.3 V I/O, LGC = 1 (2.4 / 0.6 V) gives more noise margin than the default 1.4 / 0.4 V on EN
and the I²C lines; optional firmware choice.

**n4. Open/short detection config** (AW p.16): the GCC 0x05–0x80 / PWM ≥ 0x20 recommendation is indeed for detection
accuracy at PVCC 4.2 V, as the audit says; detection is also optional (OSDE = 0x by default).

**n5. LED register index**: in the AW map, LEDn = (SW − 1) × 18 + (CS − 1) (p.16 Fig. 16); with CS16–18 unused,
indices 15–17 of every SW column are skipped. Firmware.

**n6. QFN footprint details**: no silk pin-1 mark (Fab chamfer only — acceptable on the back under the cell, but add a
silk dot if silk is kept there); mask is left to the board default — the land pattern (p.38) wants NSMD with ≤ 0.05 mm
expansion, so keep the board's mask expansion ≤ 0.05 mm on this part. Thermal vias are on the board, not in the footprint
(gate 7, "as many as possible", p.35).

**n7. LED courtyard** is 0.05 mm beyond copper (vs. the usual 0.25 mm); accepted deliberately for the 2.44 mm pitch, as
the audit says. Make sure JLC's 0.15 mm SMD-to-SMD rule is checked at gate 7, not just KiCad's courtyard DRC.

**n8. SW bus IR drop**: the nine SW lines carry 128 mA pulses round the ring; 50 mm of 0.15 mm 1 oz trace ≈ 0.2 Ω ≈
25 mV per line, which comes straight off the m1 headroom. Gate 7: width the SW bus generously.

**n9. "Schottky" in the review brief**: the brief's "VBUS minus a Schottky (≤ 4.95 V)" is stale; the audit's "VBUS − D3"
is right and D3 is silicon (see m3). Nothing to fix in the audit.

**n10. REXT accuracy at 47 k** remains an open bench item (only 10 k and 5 k are characterised, p.35), as the audit says.
ISET is a reference-voltage pin so 1/R scaling should hold; verify Imax on the first board.

## Verdict

**PASS WITH FIXES** — pin map, address, footprints, pad polarity and every headline number (8.51 mA, 0.0984, 0.837 mA,
113 mA, 128 mA, 279 mW) recompute correctly; the fixes are documentation corrections (m1, m2), firmware settings
(m3, m5, n1–n3) and one optional bulk-capacitor upgrade (m4). No hardware blocker.
