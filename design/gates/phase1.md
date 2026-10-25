# Gate 1 — parts (LiPo change only)

Scope: the parts this change touches. Everything else carries its rev-2 audit (`bom/parts.yaml` notes).

| item | evidence |
|---|---|
| Cell datasheet opened | `datasheets/LPR302823.pdf`, read in full (1 page) → `parts/bt1-lipo-cell.md` |
| Charger datasheet opened | `datasheets/LGS4056H.pdf` (from LCSC C5124109) → `parts/r8-rprog.md` |
| R8 part verified | LCSC C25762 = UNI-ROYAL 0402WGF1802TCE, 18k ±1% **0402** (product page checked 2026-10-22) |
| Q2 / D2 heights (they sit under the cell) | `datasheets/CJ2101.pdf` A = 0.900–1.100. `datasheets/BAT54SW.pdf` SOT323 A 0.8–1.1 |
| Calculations | I_CC = 900/18k = 50 mA vs 70 mA cell max. Charger P = 130 mW worst case. Termination 5 mA. Recharge 4.02 V. SC/TC revival of a tripped PCM |
| Rejected options logged | LGS4056H-4.35 (PCM trip conflict), in `decisions.md` |

## Review — independent (stronger model, fresh context), 2026-10-22

| # | sev | finding | resolution |
|---|---|---|---|
| B1 | BLOCKER | circuit.py / parts.yaml / design.yaml still carry 22k + MY-2032 clip | **Fixed.** The review ran while the edits were in flight. circuit.py R8 = `r_18k` "18k", BT1 = `battery_pads` "LPR302823". parts.yaml gains `r_18k` C25762 and `battery_pads`. design.yaml says 50 mA |
| M1 | MAJOR | "resume 2.50 V" is a charger-detect release, not a typo; revival works via SC/TC, and the audit's reasoning was wrong | **Fixed** in bt1-lipo-cell.md and r8-rprog.md. Firmware owns the 2.75 V floor |
| M2 | MAJOR | worst-case charger P is 130 mW (CC from V_TC min 2.65 V), not 118 | **Fixed** in r8-rprog.md and brief.md |
| m1 | MINOR | C16/C17 10 V 0603 X5R → ~4–6 µF effective vs "10 µF effective" | **Disputed**, see decisions.md (pre-existing, bench-proven on rev 1) |
| m2 | MINOR | worst-case chord half-width is 12.4, not 10.7 | **Fixed** (noted in the audit). The fit check already uses the full union envelope |
| m3 | MINOR | PCM strip is the pouch's thickest region | **Noted** in the audit. Pads are outside the envelope |
| m4 | MINOR | 4.2 V on a 4.35 V cell → longer CV tail | **Noted** in r8-rprog.md (charge time ≈ 2.5 h + tail) |
| N | NOTE | SOT-323 max 1.1 mm; intent said ~1.0 | **Fixed** in intent.md |

**Gate 1: PASSED** after fixes. No re-review: the fixes are documentation corrections, plus the netlist edits that phase 2's sync check covers.

---

# Gate 1 addendum, 2026-10-24: one-button BOOTSEL, silicon D2/D3, button TVS

This covers the parts the change adds or swaps. Stock and price were checked
2026-10-24 through the JLCPCB parts API and the LCSC product endpoint.

| ref | part (LCSC) | datasheet opened | pinout → footprint | key numbers used |
|---|---|---|---|---|
| D2 | BAV99W,115 Nexperia (C8662, 81k, ext) | `BAV99W.pdf` | Table 2: 1 A1, 2 K2, 3 K1/A2, the same as BAT54SW → `SOT-323_BAT54SW` unchanged | IR ≤ 30 nA @25 V/25 °C, ≤ 30 µA @25 V/150 °C; VF ≤ 715 mV @1 mA |
| D3 | 1N4007WS MDD (C193404, 908k, ext) | `1N4007WS_MDD.pdf` | cathode bar; `D_SOD-323` pad 1 = K → VSYS (unchanged) | VF 0.80 V @0.1 A typ (Fig. 3), ≤ 1.1 V @1 A; IR ~0.02 µA @25 °C, ~0.6 µA @75 °C (Fig. 2); 1 A, IFSM 25 A |
| D4 | BAV70W,115 Nexperia (C28064, 17k, ext), was Diodes C93029 (100 left) | `BAV70W_nexperia.pdf` | Table 2: 1 A1, 2 A2, 3 CC, the same as Diodes DS30063 | IR ≤ 30 nA @25 V/25 °C |
| D5 | 1N4148WS JSCJ (C2128, 2.96M, **basic**) | `1N4148WS_jscj.pdf` | `D_SOD-323` pad 1 = K → BTN_SENSE | VF ≤ 715 mV @1 mA, IR ≤ 25 nA @20 V |
| D6 | PESD5V0S1BL,315 Nexperia (C84374, 94k, ext) | `PESD5V0S1BL.pdf` | non-polar; `D_SOD-882` = stock KiCad land, identical to ds Fig. 10 (0.4 × 0.7 pads, 0.7 mm pitch) | VRWM 5 V, VBR 5.5–9.5 V, VCL ≤ 14 V @12 A, 30 kV contact; IRM 5 nA typ / 100 nA max @25 °C, Fig. 6 temperature slope |
| U8 | 74LVC2G14GW,125 Nexperia (C6085, 2.8k, ext) | `74LVC2G14_nexperia.pdf` | Table 3 SOT363: 1 1A, 2 GND, 3 2A, 4 2Y, 5 VCC, 6 1Y → stock `SOT-363_SC-70-6` | VT+ 1.30/1.76/2.20, VT− 0.60/1.04/1.50 @3.0 V (−40…85 °C); II ±1 µA max; IOFF; A max 1.1 mm |
| Q6, Q7 | BSS138W-7-F-ES ElecSuper (C5224279, 16k, ext; the existing Q3/Q5 part) | `BSS138W_elecsuper.pdf` (+ `BSS138W_diodes.pdf`) | pin 1 G, 2 S, 3 D = `SOT-323_MOSFET` (verified, review N2 closed) | VGS(th) 0.8/1.0/1.5 V; IDSS ≤ 1 µA @60 V; IGSS ±10 µA @±20 V |
| Q8 | CJ2101 (C52641, existing part) | `CJ2101.pdf` | unchanged | |
| Q4 (review F2) | LBSS84WT1G LRC (C383208, 8.9k, ext), was CJ2101 | `LBSS84WT1G.pdf` | p.1: 1 G, 2 S, 3 D = `SOT-323_MOSFET` (same land) | VGS(th) −0.8/−2.0 V @250 µA; IDSS ≤ 0.1 µA @−25 V; VGS ±20 V; RDS(on) 2/6 Ω @−5 V (Q4 passes ~30 µA) |
| R28 | 680k 0402 UNI-ROYAL 0402WGF6803TCE (C4131, 128k, ext) | — | R_0402 | |
| R26 100k, R27 4.7k, R29 1M, R30 1k, C76 10n, C77 100n, C75 10 µF | BOM lines C25741, C105871, C26083, C11702, **C15195 (new, basic)**, C1525, C19702 | — | — | C75 = CL10A106KP8NNNC, X5R ±10 %, T 0.8 ± 0.1. R27/C76/R29 values changed by review F4/F5 |

**Calculations** (re-derived in the simulator, `design/sim/button/README.md`):
- Off-state leaks: EN ≤ 0.03 V at 85 °C. Q4 (LBSS84WT1G) VGS −225 mV against a −580 mV limit when hot, with 1 µA of Q5 IDSS.
- BOOTSEL window 2.2–10.3 s (2.0–19.4 s with U8 II at its ±1 µA spec max).
- ESD into BTN_N ≤ 22 mA.
- VSYS = VBUS − 0.8 V.
- D3 dissipates ≤ 0.12 W at 140 mA.

**Heights:** everything new that sits under the cell is ≤ 1.1 mm (SOT-363 A max 1.1, SOD-323 1.10, 0603 0.9). `gen_lipo_fit_svg.py` reports no clash.

**Extended parts added:** BAV99W, 1N4007WS, PESD5V0S1BL, 74LVC2G14GW, the 680k, BAV70W (Nexperia), and LBSS84WT1G (Q4). BAT54SW and B5819WS leave, and SKRPAME010 (SW1) leaves.

**Re-review 2026-10-24: PASS** (see design/gates/phase8.md, "Re-review of the fixes").
