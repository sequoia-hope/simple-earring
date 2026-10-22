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
