# Gate 8 — simulation (power button / BOOTSEL / power path)

Status: **IN PROGRESS.** The power-button testbench is done and found a defect
in the committed design. Other triggered simulations (LED rail inrush,
charger thermal) have not started.

## design/sim/button — evidence

| check | evidence |
|---|---|
| netlist provenance | generated from `scripts/circuit.py` by reference designator (`run.py: board_netlist`); U1 replaced by the behavioral RP2350 in `mcu.lib` |
| model calibration | `models.lib` comments: CJ2101 Vto offset to ID = 250 µA at VGS(th); BAT54 / B5819WS reverse current matched to Nexperia Fig. 2 / Yangjie Fig. 4 at 4 V; silicon EG 0.85 to match the BAV70W temperature trend |
| corners | typ 25 °C; cold −20 °C (high thresholds, slow boot, t_samp 10 ms); hot 85 °C (low thresholds, fast boot, t_samp 50 µs); cell 3.0 / 3.7 / 4.2 V and open |
| run | `python3 design/sim/button/run.py`: 117 runs, 107 pass. **onebutton_fix: all pass.** asbuilt / onebutton: the 10 failures all have one root cause, the hot self-start (idle_off ×6, fw_off ×2, force_off_hung, bootsel_usb_sw1 at the hot corner) |
| off-state EN vs T | as committed: 0.04 V @25 °C, **0.83 V @70 °C**, 2.27 V @85 °C vs the NCP730 EN min threshold of 0.7 V. Both diodes silicon: ≤0.03 V throughout |
| BOOTSEL fire time | 2.1 s (hot) / 4.7–4.9 s (typ) / 8.2–8.5 s (cold) into the hold, including U8 input leakage |
| report | `out/sim/button/index.html` (dashboard `/sim/button/`), `design/sim/button/README.md` |

## Findings

| # | sev | finding | status |
|---|---|---|---|
| S1 | **BLOCKER** | Hot self-start of afabd86: D2b + D3 reverse leakage → EN ≥ 0.7 V at ~70 °C | open, needs a user decision on D3 (see README) |
| S2 | NOTE | 5 ms tap stretched to ~20 ms by C27/R24; latching depends on boot-to-PWR_HOLD time | firmware obligation |
| S3 | NOTE | Connecting the cell will usually power the board on (C27 charging lags LATCH_G) | bench check |
| S4 | MAJOR | ESD into BTN_N acts as a press; ~24 A peak through D4 (IFSM 2 A). Affects afabd86 | open: bidirectional TVS on BTN_N |
| P1 | proposal | one-button BOOTSEL + force-off: passes everything with the S1 fix | waiting on user |

## Independent review (stronger model, fresh context), 2026-10-24

B1 (hot self-start) CONFIRMED with typical parts (onset ~72 °C typ, ~68 °C
for a min-threshold LDO). The proposal is CONFIRMED in the model. Fixed after
the review:
- M1: the timer leakage (now 560k/10 µF with an input-leakage corner).
- N1: RP2350 alive at 2.7 V.
- N3: the charger input is high-Z.

Still open:
- M2: ESD TVS.
- M3: firmware has to change together with the proposal.
- N2: fetch the BSS138W datasheet.

The full table is in `design/sim/button/README.md`.

**Gate 8 is NOT passed:** S1 and S4 are open, and the other triggered
simulations (LED rail inrush, charger thermal) haven't started.
