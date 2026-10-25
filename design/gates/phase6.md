# Gate 6 — placement (LiPo change)

| check | evidence |
|---|---|
| DRC on the placed + pre-routed board | `kicad-cli pcb drc --severity-error`: **0 errors** (248 unconnected = unrouted, expected) |
| placement diff vs 4538da2 | only SW2 (replaced, now B3U) + 5 new latch parts. C17 0.07 mm relaxer nudge. LED/cap rotations differ ≤ 0.5° = rounding in the committed board |
| cell envelope | `gen_lipo_fit_svg.py`: no clash. SW2 0.37 mm, J1 3.78 mm from the worst-case envelope. 22 parts under the cell, all ≤ 1.1 mm |
| pre-route warnings vs baseline | baseline: "no safe VLED via spot near LED3" + VBUS trunk 2 segs. Now: VBUS trunk 2 segs only. (The BT1 pads blocked LED1/2/34's coarse via search; fixed with a polygon-accurate fallback in route.py, used only where the coarse rule fails) |
| renders | out/render_place_top.png, out/render_place_bottom.png, out/lipo_fit.svg |

## Review — independent (stronger model, fresh context), 2026-10-22

No blockers. Reviewer verified the B3U footprint against Omron p.3 (pads 0.8 × 1.7 at 4.2/2.6, body 3.0 × 2.5, actuator 0.70 proud, body face on the edge to 0.002 mm). The back centre is genuinely free.

| # | sev | finding | resolution |
|---|---|---|---|
| M1 | MAJOR | BT1 pads 0.265 mm from the tip LEDs' VLED vias (the via fallback ran after the pad sweep and squeezed them in) | **Fixed.** Pads re-swept against all copper incl. tracks and vias, now 1.2 × 1.6 at (+6.0,−16.0)/(−5.6,−16.7). `route.py` keeps vias ≥0.6 mm off BT1 in both coarse and precise via searches. Measured as built: **0.61 / 0.62 mm** to the nearest other copper. *(Also caught while fixing: shapely and KiCad pad rotations run opposite ways, so the first re-sweep's pads landed mirrored at 0.34 mm. Corrected via local rotations, documented in gen_footprints.py.)* |
| m2 | MINOR | "x > −5.6 kept clear" is false (Q5.2 at −4.55, R25 at −4.94) | **Claim corrected** in brief §7. Harmless: those pads are PWR_HOLD/BTN_SENSE, the nets pins 32/33 carry |
| m3 | MINOR | − lead path pinched between SW2 and J1; pads small and near the edge | Pads enlarged to the max that fits at ≥0.6 mm (1.2 × 1.6; 1.3 × 2.0 has no legal spot). Brief: the − lead goes **over SW2 under kapton**. 0.7–0.8 mm edge margin |
| m4 | MINOR | J1 clearance quoted by courtyard (3.78) again | **Fixed:** fit script measures courtyard ∪ real pad copper. J1 now 2.87 mm |
| m5 | MINOR | ±0.5 mm hand slop is realistic; then the cell reaches the edge | **Accepted and documented** (brief §7): binding constraint is the edge/case. Cup Ø29.5+, or a jig |
| m6 | MINOR | SOT-666 height 0.6 is wrong (1.0 max); U5 sits under the PCM edge | **Fixed** in the HEIGHT table. Noted in the brief. Still ≤1.1 cap |
| N7–10 | NOTE | B3U verified; SWDIO locked via under Q5 (tented, DRC clean); VBATT is the longest new net; cup ≥5.2 mm, actuator nub offset | noted (brief §Downstream) |

After fixes: DRC on placed+pre-routed board **0 errors**; placement diff vs 4538da2 = SW2 + 6 new parts + C17 0.025 mm.

**Gate 6: PASSED** after fixes. The placement itself is ready to route, pending the user's sign-off on the brief (gate 4).

---

# Gate 6 addendum, 2026-10-24: one-button BOOTSEL + button ESD placement

| check | evidence |
|---|---|
| method | `tools/scan_spot.py` per part in signal order, with the previous parts placed (pad polygons, tracks, vias, holes, courtyards, edge). For back parts near the chip, a centre keepout around U1 (±5.6 × −6.0…5.0, centre-tested) keeps the area under the MCU for pin-escape vias. Spots are in `scripts/place.py` ONEBTN, with the reasons inline |
| placement diff vs afabd86 | −SW1, +14 new parts. **C17 moved 0.115 mm** (relaxer, as at afabd86). Nothing else moved |
| DRC (placed + locked pre-routes) | `kicad-cli pcb drc --severity-error`: **0 errors**, 268 unconnected (unrouted; it was 248). The first pass found two courtyard overlaps the scanner missed (D6–C27, C77–U8), fixed by 0.25 mm nudges |
| cell envelope / heights | `gen_lipo_fit_svg.py`: no clash. Under the cell: C75, C76, C77, D5, Q7, Q8, R26, R27, R28, R30, U8 (≤ 1.1 mm). HEIGHT table extended for SOT-363, SOD-323, SOD-882 and 0603 |
| ESD topology | D6 at (−6.00, −11.75) back (C27's old spot, on the SW2.2→R30 line), 3.45 mm from SW2.2; nothing nearer is legal in the crowded tip. C27 moved behind R30 to (−6.75, −8.5). **Routing constraint: SW2.2 → D6.1 → R30.1**, with nothing else on BTN_EXT, plus a GND via at D6.2 |
| front | Q6/R29 in SW1's old top-centre spot, (−1.0, −11.0) / (−3.25, −12.75), after review F1 caught the first spot sitting on the silk art |
| pre-routes | `route.py --no-freeroute`: "power-ring stubs: 8 added, 3 blocked", same as before |
| renders | out/render_place_top.png, out/render_place_bottom.png |

Review (adoption, 2026-10-24): F1 and F7 fixed as above. Re-check after the
fixes: DRC **0 errors**, 268 unconnected. Remaining DRC warnings on the new
parts are silkscreen-only (D6/R30/R18 and D5/U5 silk, pin-1 dots over copper on
Q6/Q7/Q8): gate-9 work.
After review F2: Q4 → LBSS84WT1G on the same SOT-323_MOSFET land, so its spot
is unchanged. Board regenerated (gen_board → place → pre-route): DRC 0 errors,
268 unconnected. Placement diff vs afabd86: −SW1, +14 parts, C27 moved 3.3 mm
to (−6.75, −8.5) on purpose (F7), C17 0.114 mm (relaxer). Cell fit: no clash.

**Re-review 2026-10-24: PASS** (see design/gates/phase8.md, "Re-review of the fixes").
