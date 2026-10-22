# R8 — charger program resistor, 22k → 18k

**Part:** UNI-ROYAL 0402WGF1802TCE, LCSC **C25762**, 18 kΩ ±1%, 0402, 62.5 mW
(LCSC product page checked 2026-10-22: value, tolerance and package confirmed
as 0402, not 0603).

**Charger datasheet:** `design/datasheets/LGS4056H.pdf` (Legend-Si LGS4056H,
fetched from LCSC C5124109 2026-10-22).

## Calculation

- Datasheet: for I_BAT < 300 mA, I_BAT = 900 / R_PROG (mA, R in kΩ), and the
  CC table gives 9k → 100 mA, consistent with that formula.
- 900 / 18 = **50.0 mA**, 0.36C on 140 mAh.
- The datasheet gives **typical values only** for I_CC, with no min/max, so
  the charger's accuracy is unspecified. The 1% resistor adds ±0.5 mA. The
  margin to the cell's 70 mA limit is 40% over nominal, which covers a ±20%
  charger spread with room left over.
- Power in R8: V_PROG ≈ 1 V (formula form V_PROG/R × 900 at the regulation
  point) → 1² / 18k = 56 µW. Trivial.
- Termination at I_CC/10 = 5 mA. Recharge at 95.7% × 4.20 = 4.02 V.
- Below V_SHORT 0.6 V: 5% I_CC = 2.5 mA. Trickle below V_TC 2.90 V typ
  (2.65–3.15) at 10% = 5 mA. A tripped PCM presents ~0 V until it sees a
  charger, and the SC → TC → CC sequence revives it (see
  bt1-lipo-cell.md; mechanism corrected after gate-1 review).
- Charge time ≈ 140 mAh × ~0.9 (4.2 V on a 4.35 V cell) / 50 mA ≈ 2.5 h of
  CC, plus a CV tail to 5 mA that runs longer than on a 4.2 V cell.

## Thermal (charger)

The linear charger dissipates (VCC − V_BAT) × I, with VCC = VBUS
(circuit.py, U2 pin 4). Worst case is the lowest cell voltage at full CC, and
CC can start as low as V_TC min 2.65 V: (5.25 − 2.65) × 0.050 = **130 mW** in a
DFN-2×2 (corrected from 118 mW after gate-1 review). At 41 mA it was 107 mW. The LGS4056H has thermal regulation, so this costs speed at
worst, never safety.

## Rejected: LGS4056H **-4.35** variant

The datasheet offers a 4.35 V CV version. This cell's PCM overcharge trip is
4.355 ±0.05 V (minimum 4.305 V), so a 4.35 V CV point could hit the PCM in CV.
4.20 V stays.
