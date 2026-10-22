# Mechanical and layout brief: LiPo power source

*Phase 4. Drafted 2026-10-22, **revised after the gate-4 review and the
SW2 → power-button decision**. Status: **signed off by the user 2026-10-22.** Routing deferred (user is building a new autorouter).*

Renders (dashboard :8618): `lipo_fit.svg` (cell envelope against the back
side, from `scripts/gen_lipo_fit_svg.py`), plus `render_place_bottom.png` and
`render_place_top.png` (placement, unrouted).

This is a delta brief. Rev 2's outline, stackup, assembly sides, LED geometry
and front placement are unchanged (`docs/PLAN.md`, `design.yaml`).

## 1. Outline: unchanged
Ø30.5 teardrop with the USB-C tip. The cell fits inside it, so the board
doesn't grow.

## 2. Mounting holes: none (unchanged)

## 3. Connectors and user controls

| what | where (board coords, front view, centre-relative) | notes |
|---|---|---|
| J1 USB-C | unchanged | |
| **BT1 + pad** (VBATT) | (+6.0, −16.0), rotated with the right tip straight | 1.2 × 1.6, pasted (comes pre-tinned) |
| **BT1 − pad** (GND) | (−5.6, −16.7), rotated with the left tip straight | 1.2 × 1.6, pasted |
| **SW2 power button** | body centre (−7.71, −13.70), rot −123.6° | Omron **B3U-3000P** side-push; the actuator overhangs the left tip edge by 0.7 |

- Pads were swept against **all B.Cu copper**: pads, locked tracks and
  vias. The tip LEDs' VLED vias are placed *after* the pads, and `route.py`
  holds every via **≥0.6 mm off BT1**, because these are hand-soldered pads.
  An earlier pass let those vias land 0.27 mm away (gate-6 M1). As built,
  **+ is 0.61 mm and − is 0.62 mm from the nearest other copper** (both
  J1's shell legs, which are GND), and 0.7–0.8 mm from the board edge.
  1.2 × 1.6 is the largest pair that fits at that clearance; 1.3 × 2.0 has no
  legal spot. The two pads are on opposite sides of J1.
- Wires: the cell's leads leave the flat (PCM end, facing the tip). The +
  lead runs up the right side of J1. The **− lead runs over SW2's body under
  the kapton, not through the 0.9 mm slot between SW2 and J1.** Trim both
  to length.
- The button is the soft-latch power control (`decisions.md`): press to wake,
  CPU holds power on, long press for off. It replaces the MSK12C02 slide
  switch, which the cell would have covered at every legal angle.

## 4. Assembly sides: unchanged (two-sided JLC SMT)
Hand steps after assembly: solder both cell wires, trim, kapton over the
joints, apply tape, press the cell down.

## 5. Layers: unchanged (4-layer JLC04161H-7628)

## 6. Density: unchanged

## 7. Floorplan

**Front: unchanged.** The LED chain keeps its re-pitch around the old slide
switch's peg holes, so every locked LED arc and the IMU's mirrored anchor stay
put, even though the B3U has no holes.

**Back:**
- **The cell** sits centred, **0.25 mm away from the tip**, with its **flat
  square to the tip axis**. The worst-case envelope is Ø28 ±1 and flat-to-far
  23 ±1, unioned over every legal combination, plus 0.3 mm of hand placement.
  The far edge reaches r 15.05 against the 15.25 edge.
- **The worst-case envelope clears SW2 by 0.37 mm and J1 by 2.87 mm,**
  measured to courtyard *and* real pad copper.
- **Hand slop is optimistic without a jig** (VHB has no reposition window).
  At ±0.5 mm the cell can reach the board edge (r 15.25) while SW2 still has
  ~1 mm. So the binding constraint is the edge and the case cup, not SW2:
  the cup must take Ø29.5+. A simple printed alignment jig would restore the
  0.3 mm assumption.
- **Under the cell (22 parts, all ≤ 1.1 mm)**: 0402s, U5 (SOT-666), U6 (LGA,
  0.86), the SOT-323s Q2 / D2 / Q4 / Q5 / D4 (1.1 max per datasheet), and
  TP1–3 (flat).
- **The soft latch** (Q4, Q5, D4, R24, R25, plus C27 by the button)
  clusters behind the MCU's west side, next to GPIO20/21 (pins 32/33). Every
  spot came from `tools/scan_spot.py` run in signal order against the real
  copper and locked pre-routes. *(Corrected after gate-6 review:* the
  scan's keepout was on part centres, so Q5's pad 2 and R25 reach x −4.55 /
  −4.94, not "x > −5.6 kept clear". Not a problem: pins 32/33 carry exactly
  the PWR_HOLD / BTN_SENSE nets those pads are on, so their vias land among
  them.)
- **No other part moved** from rev 2. Placement diff against `4538da2`: only
  SW2 (replaced) and the six new parts, plus a 0.025 mm relaxer nudge on
  C17.

### What removing BT1 frees
- The Ø8 GND centre pad and its six solder bumps are gone, and with them the
  two `route.py` rules they imposed: no vias inside r 4.6, and no vias on the
  clip feet. The back centre is now routable.
- PLAN.md traced rev 2's two long open nets (LIGHT, VBUS_SENSE) to that
  blocked disc. **Expected: they route.** This is verified in phase 7, not
  assumed.

## 8. Thermal
Charger worst case is 130 mW at 50 mA (CC from 2.65 V on a 5.25 V port).
U2 is on the front, opposite the cell. LGS4056H thermal regulation protects
the IC, not the cell. **Bring-up item:** thermocouple on the cell during a
charge from flat.

## 9. Art zone: no change

## 10. Silkscreen (B.Silk). Executed in phase 9
- `+` / `−` beside the pads, readable from the back.
- **Cell alignment marks**: ticks at both ends of the flat and at the
  envelope's corners nearest SW2 and J1, since that's what the 0.3 mm slop
  assumes. Silk under the cell is fine; it's covered by tape.
- **The back-side URL arc is hidden under the cell.** Board identity moves to
  a visible spot (front or tip band), or is accepted as hidden. Decided in
  phase 9.

## 11. Keepouts and height rules
- **Under-cell height cap: 1.1 mm.** Nothing taller may go inside the
  worst-case envelope. Today the tallest under the cell are the SOT-323s at
  1.1 max. SW2 (1.35 max) and J1 sit outside.
- U5 (SOT-666, 1.0 max) sits just under the flat edge, where the PCM seal
  makes the pouch stiffest. It's legal under the cap; noted for fitting.
- **Tape: 3M VHB 4956, 1.5 mm**, a stock thickness. That leaves 0.4 mm over
  the cap; foam compresses 30–50% while the cell is pressed on, so 1.2 mm was
  not real margin. Add a thin kapton disc under the pouch so its laminate
  edge can't reach test pads or J1's leg fillets.
- **Stack: 4.7 mm** (1.5 tape + 3.2 cell). Rev-2 coin cell + clip was ~3.8 mm,
  so **+0.9 mm for 140 mAh nominal / ~120 mAh at 4.2 V, against 85 mAh**.

## 12. Test and debug
TP1–TP3 (RUN / SWCLK / SWDIO) are under the cell. They're reachable before
the cell is fitted, or after peeling the tape. UF2-over-USB stays the normal
path. **Accepted.**

## Downstream
- **Full re-route** (`build.py`, ~2.5 h per freerouting attempt last time).
- Firmware: power latch (GPIO20 hold, GPIO21 button) is now **required**, or
  the board turns off when the button is released. Plus the LiPo gauge.
  Tracked in `intent.md`.
- Case (`gen_case.py`): new rear cup ≥5.2 mm deep (4.7 nominal, no thickness
  tolerance in the datasheet, ~10% pouch swelling), Ø29.5+, no cell preload
  pad, and an aperture or moulded nub for the B3U actuator (0.7 mm proud,
  centred ~0.6 mm toward the back from the board mid-plane). Follow-on.
