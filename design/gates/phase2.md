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

---

# Gate 2 addendum, 2026-10-24: one-button BOOTSEL, silicon D2/D3, button TVS

**Changes**
- SW1 deleted.
- New block "one button: long hold = BOOTSEL / force-off": Q8, R26, R27, R28, C75, D5, U8, C77, Q7, C76, R29, Q6.
- Latch block: SW2 → BTN_EXT, plus D6 (TVS) and R30. D4 A1 → PRESS_N.
- D2 → BAV99W, D3 → 1N4007WS.
- Flash block: R3's BOOTSEL_SW end becomes a label.

| check | evidence |
|---|---|
| netlist vs circuit.py | `gen_schematic.py`: "netlist verified against circuit.py: **97 nets match**" (157 components) |
| ERC | `kicad-cli sch erc --severity-error`: 7 errors, all `power_pin_not_driven` on the power symbols, **the same 7 as the baseline**. No new types |
| text clashes | the generator's clash checker passes (0) after placing the D5, R3, U8/C77 and D6 text |
| style | Power is on top and GND at the bottom. Signal runs left → right: PRESS_N → Q8 → BTN_SENSE → R28 ∥ D5 → BOOT_TMR → U8 → LONG → Q7 / C76 → Q6. U8's 1Y/2A pins sit side by side, so the LONG_N link is a two-pin bracket. Global labels appear only for cross-block nets (PRESS_N, BTN_SENSE, BOOTSEL_SW, RUN) |
| symbols | New: plain `D` (D3, D5) and `D_TVS` (D6). D_CC and D_SS lost the Schottky hooks: D4 has always been silicon (BAV70W), and D2 now is too. The ring-cap bank filter now excludes C75–C77 |
| renders | scratch crops of out/earring-schematic.pdf, checked |

After review F4/F5: R27 → 4.7k, C76 → 10n, R29 → 1M. Regenerated: 97 nets
match; text-clash check 0.
Review F2: Q4 → LBSS84WT1G (`latch_pfet`), drawn with the same Q_PMOS_HS
symbol. Regenerated: 97 nets match.

**Re-review 2026-10-24: PASS** (see design/gates/phase8.md, "Re-review of the fixes").
