# Gate 8 — simulation (power button / BOOTSEL / power path)

Status: **power-button testbench done; S1 and S4 fixed in the netlist
(2026-10-24).** The other triggered simulations (LED rail inrush, charger
thermal) have not started, so the gate as a whole is still open.

## design/sim/button — evidence

| check | evidence |
|---|---|
| netlist provenance | generated from `scripts/circuit.py` by reference designator (`run.py: board_netlist`). U1 is replaced by the behavioral RP2350 in `mcu.lib`. The pre-change design is the `afabd86()` patch |
| model calibration | `models.lib` comments: CJ2101 Vto offset to ID = 250 µA at VGS(th); BAT54/B5819 reverse current matched to Nexperia Fig. 2 / Yangjie Fig. 4; silicon EG 0.85; **LBSS84WT1G** Vto offset −0.02 V to ID = 250 µA at VGS(th); **1N4007WS** forward fitted to MDD Fig. 3 with the reverse leak from Fig. 2; **PESD5V0S1BL** clamp from Table 6, with the leak scaled by Fig. 6 |
| corners | typ 25 °C; cold −20 °C (high thresholds, slow boot, t_samp 10 ms, C75 × 1.10); hot 85 °C (low thresholds, fast boot, t_samp 50 µs, C75 × 0.70, TVS IRM max); cell 3.0 / 3.7 / 4.2 V and open |
| run | `python3 design/sim/button/run.py -j 4`: **54/54 pass** after the review fixes (board: every scenario × corner, plus the review's II-limit / pull-up-on / click-then-hold scenarios; afabd86 reference runs). Hot corner now also has 1 µA of BSS138W IDSS at 85 °C and Q4 = LBSS84WT1G at −0.68 V |
| off-state EN vs T | board ≤ 0.03 V at 25–85 °C. afabd86 reached 0.83 V at 70 °C and 2.27 V at 85 °C (NCP730 EN min 0.7 V). With either diode put back to Schottky, 0.83 / 1.50 V at 85 °C: both swaps are needed |
| BOOTSEL fire time | 2.2–2.4 s (hot) / 5.1–5.4 s (typ) / 10.1–10.3 s (cold) into the hold; 2.0–19.4 s with U8 II at its ±1 µA spec max |
| ESD ±8 kV (IEC contact, into the pad) | clamp −19.0 / +18.4 V at BTN_EXT; ≤ 22 mA through R30; Q4 VGS ≥ −0.19 V; board stays off (typ and hot) |
| report | `out/sim/button/index.html` (dashboard `/sim/button/`), `design/sim/button/README.md` |

## Findings

| # | sev | finding | status |
|---|---|---|---|
| S1 | BLOCKER | afabd86 self-starts hot: D2b + D3 reverse leakage puts EN ≥ 0.7 V at ~70 °C | **fixed:** D2 → BAV99W, D3 → 1N4007WS (user decision 2026-10-24); kept as `selfstart_afabd86` |
| S2 | NOTE | 5 ms tap stretched to ~20 ms by C27/R24; latching depends on boot-to-PWR_HOLD time | firmware obligation |
| S3 | NOTE | connecting the cell will usually power the board on | bench check |
| S4 | MAJOR | ESD into BTN_N counts as a press; ~24 A through D4 | **fixed:** D6 PESD5V0S1BL at the pad + R30 1k |
| P1 | — | one-button BOOTSEL + force-off | **adopted** (user decision 2026-10-24) |

## Independent review (stronger model, fresh context): proposal stage, 2026-10-24

B1 (hot self-start) was confirmed with typical parts. Onset is ~72 °C typical
and ~68 °C for a min-threshold LDO. The proposal was confirmed in the model.

| # | finding | resolution |
|---|---|---|
| M1 | timer leakage | 560k/10 µF + `ii` corner; now 680k with an X5R bias corner |
| M2 | ESD | TVS + R30 |
| M3 | firmware polarity | obligation |
| N1 | RP2350 alive at 2.7 V | fixed |
| N2 | BSS138W datasheet missing | fetched (ElecSuper, the LCSC part) |
| N3 | charger input should be high-Z | fixed |

## Independent review: adoption, 2026-10-24

Stronger model, fresh context, artifacts only. It verified independently:
- every new pinout against footprint pad numbers and circuit.py (F11);
- off-state EN ≤ 0.12 V at datasheet limits (F12);
- RUN pulse 8–14 ms with CSn held low through the bootrom sample;
- no false BOOTSEL during the 3V3 ramp.

| # | sev | finding | resolution |
|---|---|---|---|
| F1 | MAJOR | Q6/R29 placed over the "Love Everyone" silk art, not in SW1's old spot | **fixed**: Q6 (−1.0, −11.0), R29 (−3.25, −12.75), front; no art overlap in DRC |
| F2 | MAJOR | off-state LATCH_G margin rests on an assumed CJ2101 tempco (−2 mV/°C; the datasheet gives none) and the model has no Q5 IDSS. Margin study (`design/sim/button/leakstudy.py`, 85 °C, cell 4.2 V): R24 100k reaches EN 0.67 V at −3 mV/°C with no extra leak, and 1.40 V with 1 µA extra. Both R24 22k and a Q4 with |VGS(th)| ≥ 0.8 V stay < 0.5 V through −3 mV/°C / 3 µA | **fixed** (user decision): Q4 → LBSS84WT1G (|VGS(th)| 0.8–2.0 V). leakstudy at 85 °C: EN 0.07 V through −3 mV/°C with 1 µA extra leak (0.41 V with 3 µA), and 0.09 V at −4 mV/°C with 1 µA. It only fails at −4 mV/°C with 3 µA extra (BSS84-class tempco is ~−3…−4 mV/°C). Hot idle: Q4 VGS −225 mV vs a −580 mV limit, including 1 µA Q5 IDSS. Cold power-on at a 3.0 V cell latches. No on-current cost |
| F3 | MINOR | the fire window used typical, not limit, U8 II | **fixed**: `bootsel_ii_limit` scenario, 2.0–19.4 s, documented |
| F4 | MINOR | with the pull-up left on and II at +1 µA, BOOT_TMR could exceed VT+ min | **fixed**: R27 10k → 4.7k; `pullup_left_on` passes |
| F5 | MINOR | C76 100n on U8's output: ~130 mA edges vs ±50 mA IO | **fixed**: C76 10n (C15195), R29 1M (C26083), same 10 ms pulse |
| F6 | MINOR | silicon D3: VSYS 3.67 V on a 4.5 V port; NCP730 headroom; Q2 body-diode load sharing can block DONE on weak ports; SOD-323 thermal | accepted (user decision); documented in decisions.md / PLAN bring-up |
| F7 | MINOR | TVS 4.4 mm from the pad, squeezed past C27/R18 | **improved**: D6 moved to C27's spot on the SW2.2→R30 line (3.45 mm; the crowded tip has nothing nearer); C27 moved behind R30 (−6.75, −8.5). A locked SW2.2→D6.1→R30.1 pre-route is left as a routing constraint for the new autorouter |
| F8 | NOTE | models.lib header cited TI tables; missing scenarios | header fixed; scenarios added (F3/F4, click-then-hold) |
| F9, F10 | NOTE | UX: power-on press held > 2 s ends off; no firmware yet drives GPIO20/21 | firmware obligations (PLAN item 1) |
| F13 | NOTE | RUN double-tap OTP alternative | noted |

## Re-review of the fixes (stronger model, fresh context), 2026-10-24

F1, F2, F4, F5 and F7 are **closed**. The reviewer reproduced the leakstudy table, re-checked the BSS84W calibration (247 µA at VGS(th) at every corner), confirmed DRC 0 and the 97-net match, and checked the Q4 turn-on margin by hand at 2.75 V / −20 °C (≥ 150 mV).

| # | finding | resolution |
|---|---|---|
| R1 | the "−1.3 mV/°C" tempco claim was read near the ZTC point | reworded: −3…−4 mV/°C assumed; passes to −4 mV/°C with ≤ 1 µA extra |
| R2, R8 | stale −128 mV / 2.2–10.3 s numbers without the II caveat; decisions.md proposal entry not marked superseded | fixed |
| R3 | the C76 "~33 mA" rationale was wrong physics (the peak is still VCC/25 Ω; charge and duration drop 10×) | comment corrected; accepted as a capacitive transient |
| R4 | R29/Q6 courtyards touch the "Sequoia Hope" art; pre-existing art crosses Q3 | gate-9 silk pass |
| R5, R6 | stale C76 comment; D6.2 needs a GND via ≤ 1 mm; keep RUN_KICK off LED_DATA | comment fixed; routing constraints added to PLAN |
| R7 | the Q5 IDSS 1 µA @85 °C is a judgment, not a limit | noted; the leakstudy's 3 µA column bounds it |

**Gate 8 (button testbench): PASS.** The gate as a whole stays open: LED-rail inrush and charger thermal haven't started.
