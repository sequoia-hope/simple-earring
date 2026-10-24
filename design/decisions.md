# Decisions log

## 2026-10-22 — LiPo replaces the coin cell

- **Cell: LiPol LPR302823 (round Ø28 D-cut, 140 mAh, ~3.0–3.2 mm).** User choice
  from a survey of cells that fit Ø30.5 with ~1 mm margin, PCM included.
  Alternatives considered:
  - LPR432421: Ø24, 155 mAh, but 4.3 mm thick and no datasheet found.
  - LP401523: 15×23, 100 mAh, 4.0 mm, 100 mA discharge cap.
  - LP402020 / LP502020: 20×21. Easiest to buy, but the 29.0 mm diagonal
    reaches 30.4 mm at tolerance.
  - Ø30 round family (LPR363027 225 mAh etc.): Ø30 ±1 has no margin on a
    Ø30.5 board.
  - Adafruit #1317 / #1570 and 20×25 cells: >32 mm diagonal, don't fit.
  - LCSC stocks no LiPo cells (category 57 holds two MEAN WELL packs).
- **Connection: two solder pads, no connector.** User choice. A JST-SH socket
  is ~3 mm tall and ~4×6 mm of back-side area, for a swap convenience nobody
  needs on an earring.
- **Repo: replace on main**, not a variant branch. User choice. The coin-cell
  rev 2 stays in git history at `4538da2`.
- **Flat faces the tip.** Geometry: flat chord 9 mm from centre, half-width
  10.7 mm. The opposite orientation puts the round edge into J1 unless the cell
  moves 1.5 mm down, and then the flat-end corners reach r ≈ 15 on a 15.25
  board.
- **Design to 3.2 mm thickness.** The datasheet side-view dimension "28 ±0.5"
  is a drawing error. The part name implies 3.0 and the vendor page says 3.2,
  so take the worse one.

- **R8 22k → 18k (50 mA).** User choice 2026-10-22 over keeping 41 mA.
  LGS4056H gives I_CC as typical only (no min/max), so the headroom under the
  cell's 70 mA limit is what covers it. See `parts/r8-rprog.md`.
- **Charge voltage stays 4.20 V; the LGS4056H-4.35 variant is rejected.** The
  cell's PCM overcharge trip can be as low as 4.305 V, below a 4.35 V CV
  point. This gives up the HV cell's top ~10–15% of capacity, which goes
  unused rather than being fought for.

- **C16/C17 stay 10 µF 10 V 0603 X5R** (gate-1 m1 disputed). At 5 V bias they
  give ~4–6 µF effective, against the LGS4056H's "10 µF effective". This is
  unchanged from rev 1/rev 2, both charged correctly on the bench. The
  LiPo's lower IR (<200 mΩ vs ≤700 mΩ) damps the BAT node *less*, so watch
  for CV-phase oscillation on the CHRG/DONE pins during bring-up. If it
  shows, swap C17 to the 25 V 0805 already in parts.yaml.

## 2026-10-22 — SW2 slide switch → momentary power button + CPU-held latch

- **Why:** SW2 (MSK12C02 slide, ~1.5 mm body per its 3D model; the
  datasheet has no drawing) sits at r 9.4 from centre, inside any Ø28 cell.
  A sweep against real copper found no cell angle or offset that clears both
  SW2 and J1 (gate 4 M1). Putting SW2 under the cell would need ~2 mm tape
  (5.2 mm stack). **User decision:** momentary side-push button on the tip
  edge beside J1; press wakes the CPU, CPU latches power, long press turns
  it off (power drops on release).
- **Circuit** (keeps every rev-2 node downstream of `SW_ON` unchanged, so
  D2 / R17 / R18 / R11 / R12 / C21 and the VBSENSE semantics carry over):
  - Q4 CJ2101 P-FET: S = VBATT, D = SW_ON, G = LATCH_G. R24 100k
    LATCH_G → VBATT keeps it off.
  - Power button SW2: BTN_N ↔ GND. D4 (common cathode; BAV70W after the
    gate-2 review, first drafted as BAT54CW) A2 = LATCH_G, K = BTN_N: a
    press pulls LATCH_G to ~0.5 V → Q4 on → SW_ON = VBATT → D2 → PWR_EN →
    LDO on.
  - Q5 BSS138W: D = LATCH_G, S = GND, G = PWR_HOLD (GPIO20, pin 32), R25
    100k pulldown. Firmware asserts it early in boot to hold Q4 on.
  - Button sense: D4's A1 = BTN_SENSE (GPIO21, pin 33, internal
    pull-up). Pressed → ~0.5–0.6 V (silicon VF) = low against VIL 0.8 V.
    When the board is off, D4-A1 is reverse-biased (BTN_N sits at ~VBATT
    through D4-A2 + R24), so nothing back-feeds the unpowered GPIO.
  - Off-state: zero by construction (Q4 gate at VBATT, Q5 off). The
    leakage that could false-trigger Q4 is D4-A1's reverse current through
    R24. **Revised after gate-2 review:** the first draft used a BAT54CW
    and its 2 µA @25 °C spec, but a Schottky's reverse current at 4 V is
    ~20 µA by 85 °C (→ 2 V on LATCH_G: latch turns on by itself in a hot
    car). D4 is now a BAV70W silicon pair (IR ≤ 25 nA @20 V/25 °C, ~1 µA
    at 4 V/85 °C → 0.1 V) against a ~0.2 V budget (CJ2101 |V_GS(th)| min
    0.45 V, less tempco and subthreshold). R24 stays 100k (42 µA while
    running).
  - C27 100n on BTN_N: ESD and debounce for the user-touched edge button
    (gate-2 review m3).
  - **Firmware must enable the watchdog** (gate-2 review M2): otherwise a
    hang with PWR_HOLD high can't be turned off and drains the cell to
    the PCM cut. Any reset drops GPIO20, so a crash = power off on battery.
  - USB still boots the LDO via R18 regardless of the latch (unchanged).
    VBSENSE = 0 on a running board still means "USB-powered, latch off".
- **Firmware obligations (new):** assert PWR_HOLD first thing in boot
  (the user has to hold the button until then); ignore the power-on press
  until it's released; long press → drop PWR_HOLD (power falls on
  release); auto-off for low battery (above the PCM's 2.75 V and LDO
  dropout). On a rev-2 coin board GPIO20/21 are unconnected, so this is
  harmless there.
- **GPIOs:** GPIO20/21 = pins 32/33, the unused west-column run (31 =
  CHRG). The BT1 centre pad's removal opens the back interior for their
  escape.

## 2026-10-24 — power-button simulation (ngspice) and the one-button BOOTSEL proposal

- **Testbench:** `design/sim/button/`. The netlist is generated from
  `circuit.py`, the models are datasheet-fitted with limits swept as
  typ/cold/hot corners, and the RP2350 is behavioral. ngspice comes from conda
  (`mamba create -n spice -c conda-forge ngspice`; there is no system
  package and no sudo).
- **Found a defect in the committed design (afabd86): it self-starts when
  hot.** The board turns on at about 70 °C with nobody touching it. The
  reverse leakage of D2b (BAT54) and D3 (B5819WS) reaches EN. See
  `design/sim/button/README.md`. **Not fixed yet**: the D3 fix trades USB
  headroom or footprint, so the user chooses.
- **Rejected: a VBUS-gated strap ("hold the button while plugging in").** With
  a charged cell, the press powers the board up from battery before USB
  arrives, so the bootrom has already sampled QSPI_SS.
- **Rejected: RUN double-tap (OTP BOOT_FLAGS1.DOUBLE_TAP).** It needs a
  button on RUN, which would reset the board on every UI press.
- **Rejected: firmware-only BOOTSEL** as the *only* path. It costs zero parts,
  and arduino-pico's 1200-baud touch already covers day-to-day uploads. But
  firmware that dies early would then need SWD, and the SWD pads are under the
  cell. It stays as a convenience on top of the hardware path.
- **Proposed (not adopted): a hold timer → RUN pulse + QSPI_SS strap**
  (`one_button()` in run.py).
  - Why the P-FET inverter (Q8): D4's diode-OR low is about 0.45 V, too close
    to the LVC2G14's VT− min of 0.6 V.
  - Why R27 = 10k: firmware that leaves GPIO21's pull-up on must not walk the
    timer.
  - Why 10 s: the Schmitt VT+ spread (1.3–2.2 V), the X7R tolerance and the
    input leakage together give a ~4× spread. Across corners it fires at
    2.1–8.5 s.
  - Why R28 is 560k and not 1.2M: independent review M1. U8's input leakage
    has to stay small next to the charge current.
  - Waiting on user sign-off. Adopting it reopens gates 2 and 6.
