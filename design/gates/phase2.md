# Gate 2 — schematic (LiPo change)

Changes: BT1 → `battery_pads` (LPR302823), R8 22k → 18k, SW2 slide → B3U power button + soft latch (Q4 CJ2101, Q5 BSS138W, D4 **BAV70W** (was BAT54CW, see review), R24/R25 100k, **C27 100n** on BTN_N), GPIO20 PWR_HOLD / GPIO21 BTN_SENSE.

| check | evidence |
|---|---|
| netlist vs circuit.py | `gen_schematic.py`: "netlist verified against circuit.py: 91 nets match" |
| ERC | `kicad-cli sch erc`: 7 errors, all `power_pin_not_driven`, **identical to the committed rev-2 sheet** (4538da2). Warnings: endpoint_off_grid / lib_symbol_issues, the same classes as the baseline (generated library). **No new error types** |
| style | new block "power button + soft latch": power on top, GND at the bottom, signal left → right, wires within the block, global labels only for cross-block nets (SW_ON, PWR_HOLD, BTN_SENSE). Q4 drawn source-up via a new `Q_PMOS_HS` symbol. Render checked (scratch) |
| text clashes | generator's clash checker passes (0) |
| part audits | `parts/bt1-lipo-cell.md`, `parts/r8-rprog.md`. Latch parts + B3U: see `decisions.md` (leakage budget), datasheets in `datasheets/` (CJ2101, BAT54SW = BAT54W series incl. CW, B3U-3000P) |

## Review — independent (stronger model, fresh context), 2026-10-22

Verified by the reviewer: D4/D2 pinouts against Nexperia Table 2; CJ2101 orientation (body diode blocks SW_ON→VBATT); every latch state computed (press VGS −2.55…−4.0 V, PWR_EN ≥ 2.5 V, sense pin ≤ 0.24 V vs VIL 0.8 V with the Schottky, clean power-down on release τ ≈ 64 µs, USB/dead-cell cases inside NCP730 EN ≤ VIN+0.3); off drain ~3–5 µA.

| # | sev | finding | resolution |
|---|---|---|---|
| M1 | MAJOR | false-trigger budget used BAT54 IR at 25 °C/25 V; at 4 V the BAT54's reverse current is ~20 µA by 85 °C (Fig. 2), plus Q4 subthreshold → R24=100k could switch the latch on when hot | **Fixed:** D4 → **BAV70W** silicon pair (Diodes DS30063: IR ≤ 25 nA @20 V/25 °C; ~1 µA est. at 4 V/85 °C → 0.1 V on LATCH_G). Same SOT-323, same pin order (verified p.1). Cost: sense pin reads VF ≈ 0.5–0.6 V pressed vs VIL 0.8 V. R24 stays 100k |
| M2 | MAJOR | hung firmware with PWR_HOLD high can't be turned off | **Firmware obligation** (intent.md): enable the watchdog; any reset drops GPIO20 → board powers off unless USB is in. Documented consequence: watchdog/picotool/SWD resets power the board down on battery |
| m3 | MINOR | no ESD on the user-touched edge button | **Fixed:** C27 100n BTN_N→GND beside SW2 (τ = 10 ms with R24) |
| m4 | MINOR | PWR_EN label drawn over D2; stale USB note "no VBUS→3V3 path" | USB note **fixed**. PWR_EN-over-D2 is a pre-existing rev-2 layout wart, **left** (cosmetic, not introduced here) |
| N5 | NOTE | bounce at power-on cycles the LDO; firmware must debounce and ignore the power-on press | firmware obligation, intent.md |
| N6 | NOTE | decisions.md said A1=LATCH_G, circuit.py A1=BTN_SENSE | **fixed** in decisions.md |
| N7 | NOTE | B3U min load 10 µA OK | — |

Re-check after fixes: `gen_schematic.py` 91 nets match (C27 sits on the existing BTN_N/GND); ERC 7 errors, all the baseline `power_pin_not_driven`, no new types.

**Gate 2: PASSED** after fixes.
