# Power button / BOOTSEL simulation

`python3 design/sim/button/run.py -j 4` takes a few minutes. It writes
netlists, waveforms and a report to `out/sim/button/` (dashboard:
`/sim/button/`), and exits non-zero if any check fails. `--quick` runs the
typical corner only; `-k NAME` filters scenarios.

## Why trust it

- **The netlist is not hand-copied.** `run.py` builds it from
  `scripts/circuit.py` by reference designator, so a value change there is a
  value change here. The design before 2026-10-24 (afabd86) is rebuilt as a
  patch (`afabd86()`), so its two hazards stay reproducible next to the fix.
- **Every model parameter traces to a datasheet** in `design/datasheets/`.
  Parameters that are datasheet limits rather than typicals are swept as
  corners (`typ` 25 °C, `cold` −20 °C, `hot` 85 °C). The calibrations are
  written next to each model in `models.lib`, including the two that were
  wrong at first: VDMOS Vto versus the datasheet's 250 µA VGS(th)
  definition, and the Schottky EG.
- **The RP2350 is behavioral, with its unknowns swept.** The bootrom samples
  QSPI_SS "shortly after reset" and gives no number, so the sample time is
  swept from 50 µs to 10 ms. The pull-up is swept over 32–86 kΩ
  (Table 1683). Firmware is stimulus here, not the device under test.
- **Each scenario carries explicit pass/fail checks.** Examples: the strap
  level against VIL/VIH scaled to IOVDD at the sample instant, Q4's VGS
  margin while the board is off, and the BOOTSEL fire time.

## The board as adopted (2026-10-24)

The user decided on 2026-10-24: one button, silicon D3, BAV99W on D2, and a TVS.

**Result: 54/54 runs pass**, covering 15 scenarios × corners × cell voltages,
plus the afabd86 reference runs.

### 1. Hot self-start: fixed

With the board off, no button and no USB, this is the EN voltage
(`tsweep`, typical parts, LDO forced off so the leak can be measured). The
NCP730 starts at 0.7–1.05 V.

| °C | 25 | 40 | 50 | 60 | 70 | 85 |
|---|---|---|---|---|---|---|
| **board** (BAV99W + 1N4007WS) | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 | **0.03** |
| afabd86 (BAT54SW + B5819WS) | 0.04 | 0.10 | 0.20 | 0.41 | **0.83** | **2.27** |
| board, D2 put back to Schottky | 0.03 | 0.07 | 0.14 | 0.28 | 0.56 | 1.50 |
| board, D3 put back to Schottky | 0.02 | 0.05 | 0.08 | 0.16 | 0.31 | 0.83 |

Both swaps are load-bearing; either Schottky alone still reaches the threshold
at 85 °C. The two leak paths:

- **D2b**, the clamp from VBATT to PWR_EN. A BAT54 leaks about 20 µA at
  85 °C into R17's 100k.
- **D3**, from VSYS to the dead VBUS node. A B5819WS leaks about 120 µA at
  75 °C into R19+R20 = 20k, and R18/R17 halve that onto EN.

`selfstart_afabd86` keeps the defect on record: at the hot corner the old
board turns itself on.

What silicon D3 costs: its VF is about 0.8 V at 100 mA (MDD Fig. 3), so
VSYS is about 4.2 V on a 5.0 V port and about 3.7 V on a 4.5 V one, which is
the SK6805 floor. With a weak port and a full cell, Q2's body diode shares the
load with the cell.

### 2. One button: long hold = BOOTSEL / hardware force-off

SW1 is gone. Holding the power button resets the chip with QSPI_SS strapped
low, so the bootrom comes up in BOOTSEL. **Flash is never touched.** With USB
in, the board waits as a drive until it's unplugged or rebooted. On battery,
the reset drops PWR_HOLD and the board turns off on release. That is the
hardware force-off for hung firmware the soft latch lacked (gate-2 M2;
`hung_afabd86` documents the old behaviour).

| corner | BOOTSEL fires after |
|---|---|
| hot (VT+ 1.3 V, C75 × 0.70, U8 sourcing 0.3 µA) | **2.2–2.4 s** |
| typ | 5.1–5.4 s |
| cold (VT+ 2.2 V, C75 × 1.10, U8 sinking 0.1 µA) | **10.1–10.3 s** |
| U8 II at its ±1 µA spec max (`bootsel_ii_limit`) | 2.0 s hot … **19.4 s** cold |

The C75 factor (`ctmr`) stacks the CL10A106KP8NNNC's ±10 % tolerance, X5R's
±15 % over temperature, and DC-bias loss at the 1.4–2.4 V it charges to. The
hot corner takes every loss at once (0.9 × 0.85 × 0.92). The cold corner gets
no bias credit. R28 went from 560k to 680k so the hot minimum stays above
2 s once the bias loss is counted.

Passing scenarios at every corner: power-on, a 5 ms tap (ends cleanly off or
cleanly on), firmware long-press-off, USB plug with the cell present and with
it open, 8 quick clicks with USB in (never fires), BOOTSEL with USB in (stays
there), and force-off of hung firmware on battery.

**Firmware obligations** (the hardware and firmware must change together):
- GPIO21 is **active high**, with no internal pull-up. R27 = 4.7k keeps a
  leftover pull-up from walking the timer: at most 0.42 V, and 1.1 V even
  with U8 leaking its +1 µA max through R28. That is under VT+ min, and
  `pullup_left_on` confirms it.
  Old firmware with "pull-up, low = pressed" would read the button as held
  forever.
- The long-press-off must be well under 2 s; plan on ≤ 1.5 s, since the
  earliest fire is 2.0 s at the II limit. `click_then_hold` shows a quick
  click doesn't make the next hold fire any sooner. On battery, a power-on press held
  past about 2 s goes on → BOOTSEL → off on release.
- Assert PWR_HOLD as early as possible. A 5 ms tap is stretched to about
  20 ms by C27/R24, so whether a tap latches depends on boot-to-PWR_HOLD
  time. At the hot corner's 5 ms boot it latches.

### 3. Button ESD: fixed

D6 (PESD5V0S1BL) clamps at the switch pad (BTN_EXT), and R30 (1k) isolates
BTN_N, C27 and D4 behind it. The test was an IEC 61000-4-2 contact network
(150 pF / 330 Ω, no tip inductance, so the edge is faster than a real gun's)
at ±8 kV into the pad, with the board off, at the typ and hot corners:

| | afabd86 (review M2) | board |
|---|---|---|
| current through D4 | ~24 A (BAV70W IFSM 2 A) | ≤ 22 mA (all of R30) |
| clamp at the pad | — | −19.0 / +18.4 V (part rated 30 kV contact) |
| Q4 VGS during the strike | −4.5 V | −0.19 V worst |
| strike registers as a press | yes | **no**, board stays off |

The TVS leak is modelled too: 5 nA typical and 100 nA max at 25 °C, scaled
by Fig. 6, so about 1.15 µA at the hot corner. It flows through R24, the
same path as D4's and Q5's IDSS (1 µA at 85 °C in the hot corner). Hot
idle with the cell at 3.0–4.2 V leaves Q4 (LBSS84WT1G) at VGS −225 mV
against the −580 mV check (hot |VGS(th)| min 0.68 V, less a 0.1 V margin).

### 4. Smaller observations

- A 5 ms tap is stretched to about 20 ms (C27 through R24). With PWR_HOLD
  first thing in main(), a tap will usually turn the board on.
- **First connecting the cell** gives the same pulse, because C27 starts
  empty, so a freshly assembled board will usually come up on.
- The VBUS node floats to about 0.5 V on battery through R18's back-feed
  (already documented in circuit.py).

## Rejected alternatives

- **Hold the button while plugging in USB (VBUS-gated strap):** with a charged
  cell, the press powers the board up from battery, and the bootrom samples
  before USB arrives.
- **R17 100k → 22k instead of silicon D3:** at 85 °C, EN is still 1.11 V
  with R18 re-ratioed, and 0.86 V even with D2 silicon. Not a fix.
- **RUN double-tap (OTP):** needs a button on RUN, which would reset the
  board on every UI press.

## Independent reviews

- **2026-10-24 (proposal stage):** B1 hot self-start confirmed, fixed above.
  M1 timer leakage: R28 resized and the `ii` corner added. M2 ESD: fixed
  above. M3 firmware polarity: listed as an obligation. N1: the chip's "alive"
  threshold raised from 1.8 to 2.7 V. N2: the BSS138W datasheet was missing;
  now in design/datasheets (the LCSC part is ElecSuper, VGS(th) 0.8–1.5 V,
  which the models already use). N3: charger high-Z input.
- **2026-10-24 (adoption):** see design/gates/phase8.md. Changes this
  review prompted:
  - R27 10k → 4.7k (F4).
  - C76/R29 100n/100k → 10n/1M (F5: U8 output current).
  - Q6/R29 moved off the silkscreen art (F1).
  - D6 moved onto the pad-to-R30 line (F7).
  - Three new scenarios (F3/F8).
  - **F2:** Q4 → LBSS84WT1G (|VGS(th)| ≥ 0.8 V), user decision, plus
    BSS138W IDSS in the model (1 µA at 85 °C in the hot corner).
    `leakstudy.py` sweeps Q4's threshold tempco (−2…−4 mV/°C) and extra
    LATCH_G leakage (0–3 µA) at 85 °C:

    | Q4 | −3 mV/°C, +1 µA | −4 mV/°C, +3 µA |
    |---|---|---|
    | CJ2101, R24 100k (before) | EN 3.8 V (self-start) | 3.8 V |
    | **LBSS84WT1G (board)** | **0.07 V** | 1.13 V |

## Not modelled

- Flash /CS activity beyond "XIP drives it high".
- The LED rail.
- The RP2350's real boot timing. picoem (a cycle-accurate RP2350 emulator)
  runs the real bootrom and could pin t_samp down; see the roadmap in
  docs/PLAN.md.
