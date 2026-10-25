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

---

# Gate 6 addendum, 2026-10-24 (b): WS2816C ring + three zones

| check | evidence |
|---|---|
| ring | 45 × LED_WS2816C-1313 at the same centres. Orientation per zone (k L/R/C = 0/2/0; the right chain is reversed). DO→DI gaps: L 1.24–1.87 mm, R 1.27–1.64 mm, C 3.1–7.7 mm |
| collisions | LED44 hit D3/C29: D3 → (9.25, −3.25), C29 → (10.0, 2.25), both rescanned. The relaxer nudged C18 0.15 mm and C26 0.36 mm (LED39/LED42) |
| zone drivers | via scan_spot. U9 back under U4 (shared VSYS); U10 back under U3; R33/C78/R34/C79 beside them. Q9 back (−9.25, −9.75), Q10 back (−9.0, −6.25), with R31/R32 beside them. The first front spots for Q9/R32 sat on the "Love Everyone" / "Be Gay" art and were moved |
| planes | In2: VLED_L 198 mm², VLED_R 233 mm², VLED_C 88 mm² (inner band), 3V3 disc unchanged |
| DRC | **0 errors**, 282 unconnected (unrouted; the user's GPU router routes it) |
| cell fit | no clash; under the cell: U9/U10 (0.625), C78/C79 (0.90), Q9/Q10 (1.10, at the cap), R31–R34 |
| locks | 59 footprints locked (45 LEDs + J1, SW2, BT1, U1, U2, U5, R14, L1, C11, C12, C13, R13, C22, Q1). Reasons are in place.py `LOCKED` |

**Review (stronger model, fresh context), 2026-10-24.** Gates 1 and 2 PASS.
Gate 6 PASS with conditions, all addressed:
- C1: VLED_C band re-centred to r 9.15–10.85 on the WS2816C VDD pads, with
  the outer band from 11.15 and the 3V3 disc at 8.95.
- C8: Q1 locked.
- C5 (four 0.03–0.07 mm courtyard gaps) and C3 (Q9/R31 far from LED37):
  routing notes in PLAN.
- A3: schematic VIH text corrected to 3.47 V.
- C9 / F1: stale comments fixed.
- B2 / B3 / E1 / E2: firmware and bring-up notes in PLAN.

---

# Gate 6 addendum, 2026-10-25: 19 parts front → back (room around U1)

| check | evidence |
|---|---|
| moved | U7/C25/R3 (flash), U2/C16/C17/R8 (charger), U3/C18/C19 (LDO), D3/C29/R21/R22/R19/R20 (power path, VBUS tap), U4/C20/R10 (LED_L switch). Spots: place.py `BACK`, from tools/scan_spot.py in signal order |
| heights | datasheet max: U2 0.8, U3 0.80, U7 0.60, U4 0.625, 0603 0.90, D3 1.10. All ≤ the 1.1 mm under-cell cap. gen_lipo_fit_svg.py: **clash: none**. It now exits when a part under the cell has no HEIGHT entry (it used to count it as 0) |
| front freed | front non-LED parts within r < 10: 40 → 26. Courtyard area within r < 10: 107 → 57 mm² |
| back under U1 | pads kept out of ±5.6 × −6…5 (escape vias) |
| route.py | dropped the freerouting assists anchored to the old spots: QSPI ×5, CHRG/CHRG_DONE vias + the U2 landing loop, LED_EN_L via, U3 3V3 via (with the now-dead via-spot helpers). U2 unlocked |
| DRC | **0 errors**, 90 warnings (main: 0 errors), 274 unconnected (unrouted). No new silk overlaps from moved parts. One new warning: U3's own pin-1 dot over its pad, the same library quirk Q2/Q7/D2 already have |
| renders | out/render_place_top.png, out/render_place_bottom.png |

**Review (stronger model, fresh context), 2026-10-25: PASS with conditions.**
Heights, pin-level placement, the route.py removals and DRC were all
verified independently. The reviewer also notes that VBUS, VSYS, VBATT,
PWR_EN, PATH_GATE and PROG now sit entirely on B.Cu.

| # | sev | finding | resolution |
|---|---|---|---|
| 1 | MINOR | R20 and R19's tap sat inside U1's back keepout, under the SE corner where pins 1–3 escape | **fixed**: R19 (7.0, 1.5), R20 (9.2, 0.2). Tap is 1.0 mm pad-to-pad, all pads at x ≥ 6.5. A first try touched C29's courtyard (DRC caught it) and was nudged |
| 2 | MINOR | the "every QSPI net under 4 mm" claim was false: SD1/SD2//CS are on U7's far row; SD0/SD3 cross | **text fixed** (place.py, decisions.md, PLAN routing notes). The geometry is the same for any row-facing rotation; SCLK stays on the near row |
| 3 | MINOR | C18 was 2.5 mm from U3.6, with EN/NC between | **fixed**: C18 (−7.8, 5.85) on VSYS between U3.6 and U4.A2. R10 moved north of C20 |
| 4 | MINOR | D3 carries all the LED current on USB (~0.12 W), next to U2, both under the cell | decisions.md thermal note corrected. PLAN: thermal vias on D3/U2 EP, a firmware brightness cap on USB, and the bring-up check with LEDs lit |
| 5 | MINOR | stale comments (route.py R3, place.py LOCKED/U2, PLAN beautify list, route.py U7 note) | fixed |
| 6–10 | NOTE | LED_EN_L / VBUS_SENSE cross under U1; U2's status pins face away; C9 could sit nearer; URL arc clear | routing notes in PLAN; rest accepted |

**Gate 6 (this change): PASS** after the fixes above. DRC was re-run after
the fixes: 0 errors.
