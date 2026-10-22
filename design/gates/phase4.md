# Gate 4 — mechanical and layout brief

Status: **PASSED — user sign-off 2026-10-22** ("approve and commit, don't route"). Routing is deferred: the user is building a better autorouter separately. The SW2 blocker was resolved by the user (momentary side-push button + CPU latch, 2026-10-22). The revised brief was re-reviewed together with the placement (gate 6 review), and its findings are folded in.

## Independent review (stronger model, fresh context), 2026-10-22

| # | sev | finding | status |
|---|---|---|---|
| M1 | MAJOR | −120° "window" is a knife edge: worst-case envelope is 0.06 mm from SW2, 0.11 mm from J1's courtyard, and **overlaps J1's real pads** (J1's courtyard is smaller than its copper). ±3° of rotation error loses one side | **Confirmed and worse.** Author re-sweep against real copper: across θ −90…−140°, centre offset 0–1.0 mm and slop 0.3/0.5, **no configuration clears both J1 and SW2 by ≥0.3 mm**. Even a nominal (zero-tolerance) cell overlaps SW2 at −90° and −105°. SW2's inner corner sits at r 9.4, so any ~Ø28 cell covers it |
| M2 | MAJOR | − pad 0.07 mm from J1 shell leg (same net, but mask merges and the joint heat-sinks into J1) | open: pads re-sweep against copper done (see below). Final spot depends on the SW2 decision |
| M3 | MAJOR | + pad 0.37 mm from J1 GND shell leg, 0.18 from SW2 frame tab | open, same |
| M4 | MAJOR | 1.2 mm foam over 1.1 mm parts is no margin (foam compresses 30–50%). No product named; 1.2 is not a stock thickness | accepted: tape → **3M VHB 4956, 1.5 mm** (stock). Stack → 4.7 mm. Add a kapton underlay disc |
| m | MINOR | free area is 87 mm² (two ~41–46 mm² pockets), not ~40 | noted |
| m | MINOR | SW2 height 1.4 vs 1.6 inconsistency | datasheet (`datasheets/MSK12C02.pdf`) has no drawing. The 3D model body is 1.5 mm above the board |
| m | MINOR | +65% is nominal-to-nominal; ~+40% at 4.2 V | noted |
| m | MINOR | + wire's path from the flat to its pad crosses R18 / the SW2 frame | noted |
| m | MINOR | no swelling allowance in the case cup | follow-on (case) |
| m | MINOR | U2 charger sits opposite the cell. Bench thermocouple | bring-up item |
| N | NOTE | SWD recovery means peeling the cell. State the worn orientation. Case's CELL_PAD preload must go. Silk should mark both flat ends | noted |

### Pad re-sweep against real B.Cu pad copper (author, after M2/M3)
+ (VBATT), ≥0.6 mm to other-net copper: only (−6.0, −16.0) @30° or its mirror, at 0.61 mm.
− (GND), ≥0.4 mm: (−5.8, −15.1) or (5.6, −15.7) @0°.

## Resolution of the first review
- M1 (SW2 / J1 knife edge): **resolved by design change.** SW2 → B3U-3000P side-push on the tip edge. Cell flat square to the tip, centre +0.25 mm. Envelope clears SW2 0.37 mm and J1 2.87 mm (real copper).
- M2/M3 (pads vs J1 shell legs): **resolved.** Pads swept against all copper and placed at ≥0.61 mm (see gate 6 M1).
- M4 (tape): **resolved.** VHB 4956 1.5 mm, stack 4.7 mm.
