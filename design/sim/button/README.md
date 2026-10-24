# Power button / BOOTSEL simulation

`python3 design/sim/button/run.py` takes about a minute. It writes netlists,
waveforms and a report to `out/sim/button/` (dashboard: `/sim/button/`), and
exits non-zero if any check fails.

## Why trust it

- **The netlist is not hand-copied.** `run.py` builds it from
  `scripts/circuit.py` by reference designator, so a value change there is a
  value change here. Proposals are patches in the same `c.add()` form
  (`one_button()`, `leak_fix()`), so adopting one is a copy-paste.
- **Every model parameter traces to a datasheet** in `design/datasheets/`. The
  ones that are limits rather than typicals are swept as corners (`typ` 25 °C,
  `cold` −20 °C, `hot` 85 °C). The calibrations are written next to each model
  in `models.lib`, including the two that were wrong at first: VDMOS Vto
  versus the datasheet's 250 µA VGS(th) definition, and the Schottky EG.
- **The RP2350 is behavioral, with its unknowns swept.** The bootrom samples
  QSPI_SS "shortly after reset", with no number given, so the sample time runs
  from 50 µs to 10 ms. The pull-up runs 32–86 kΩ (Table 1683). Firmware is
  stimulus, not the device under test.
- **Each scenario carries explicit pass/fail checks.** Examples: the strap level
  against VIL/VIH scaled to IOVDD at the sample instant, and Q4's VGS margin
  while the board is off.

## Findings (2026-10-24)

### 1. HOT SELF-START: this affects the committed design (afabd86)

With the board off, no button and no USB, reverse leakage lifts the LDO's EN
pin above its 0.7 V minimum threshold at about **70 °C**. The board then turns
itself on and the firmware latches it.

| °C | 25 | 40 | 50 | 60 | 70 | 85 |
|---|---|---|---|---|---|---|
| EN, as committed | 0.04 | 0.10 | 0.20 | 0.41 | **0.83** | **2.27** |
| EN, D2 → silicon only | 0.03 | 0.07 | 0.14 | 0.28 | 0.56 | 1.50 |
| EN, D3 → silicon only | 0.02 | 0.05 | 0.08 | 0.16 | 0.31 | 0.83 |
| EN, both silicon | 0.02 | 0.02 | 0.02 | 0.02 | 0.02 | 0.03 |

The independent review confirmed this with typical parts. NCP730 Fig. 11 puts
the typical EN threshold at about 0.88 V, so a typical LDO starts at about
72 °C, and a 0.7 V unit at about 68 °C. Schottky IR batch spread is 2–3×,
which leaves under 2× margin even at 60 °C.

There are two paths, and fixing either one alone is not enough:

- **D2b**, the BAT54 clamp from VBATT to PWR_EN, leaks about 20 µA at 85 °C
  (Nexperia BAT54W Fig. 2). Through R17's 100k that is 2 V on EN. This is the
  same physics gate-2 review M1 caught on D4. R17's sizing comment only counted
  EN's own 1 µA pull-up.
- **D3**, the B5819WS from VSYS to VBUS, leaks about 120 µA at 75 °C (Yangjie
  Fig. 4). The dead VBUS node is held only by R19+R20 = 20k, so it rises about
  2.4 V, and R18/R17 halve that onto EN. A side effect is that VBUS_SENSE reads
  "USB present" when hot.

The sim's fix candidate makes both diodes silicon. **D2 → BAV99W** is the
same SOT-323 series pair with the BAT54S pinout (check its datasheet before
adopting). **D3 → a 1 A silicon rectifier** gives VF of about 0.75 V at
60 mA, so VSYS is about 4.25 V on a 5.0 V port. That still clears the
SK6805's 3.7 V floor, but it needs a bigger footprint than SOD-323. On a
4.5 V port it is about 3.75 V, right at that floor (review). The alternatives
worth pricing for D3:
- A P-FET ideal diode.
- **R17 100k → 22k.** The leakage would then have to be 4.5× larger to reach
  the threshold. It costs about 150 µA while the board is on, and R18 has to
  be re-ratioed so USB still enables the LDO.
- A much stiffer VBUS pull-down, which costs mA whenever USB is plugged in.

### 2. One-button BOOTSEL (proposal: `one_button()` in run.py)

SW1 goes. Holding the power button **10 s** forces BOOTSEL: across all
corners, including the timer gate's input leakage, the circuit fires 2.1–8.5 s
into the hold. A Schmitt gate times the
hold, pulses RUN low for about 10 ms, and holds QSPI_SS low through R3 for as
long as the button stays down, so the bootrom wakes up into BOOTSEL. With USB
in, the board stays in BOOTSEL after release. On battery, the same hold is a
**hardware force-off for hung firmware**: the reset drops PWR_HOLD and power
falls on release. That closes gate-2 M2. The `hung_asbuilt` scenario
documents that the current board can't be turned off in that state.

With the leak fix in, every scenario passes at every corner and cell voltage:
power-on, a 5 ms tap, firmware long-press off, USB plug (with the cell
present and with it open), 8 quick clicks with USB in, BOOTSEL with USB in,
and the force-off. The off-state leak budget on LATCH_G is the same as as-built,
because D4's spare anode moves from the GPIO pad to PRESS_N, which is also 0 V
when the board is off.

Parts: −SW1, +U8 74LVC2G14, +Q6 Q7 BSS138W, +Q8 CJ2101, +D5 1N4148WS,
+R26 100k, R27 10k, R28 560k, R29 100k, +C75 10 µF X7R, C76 100 nF.
R28 was first 1.2M. The review (M1) flagged that U8's input leakage would
swamp it, so it is now 560k with an ii input-leakage corner of ±0.1–0.3 µA.
At the LVC II spec maximum of ±5 µA, any µA-level RC timer breaks. Real parts
are nA, but **check it at bring-up**.

**Firmware obligations if adopted:**
- GPIO21 becomes **active high**: pull-down or no pull. R27 = 10k is chosen so
  that a leftover internal pull-up can't creep the timer up (at most 0.79 V,
  under VT+ min). **Firmware has to change at the same time as the hardware**
  (review M3). Old firmware with "pull-up, low = pressed" reads 0.79 V ≈ VIL
  as held forever, and runs its long-press-off right after latching. Firmware
  that drives GPIO21 high would reboot the chip into BOOTSEL within 2–8 s.
- The long-press-off must be well under 2 s, below the hardware's 2.1 s minimum.
  On battery, a power-on press held past about 2 s goes on → BOOTSEL → off
  on release.
- Assert PWR_HOLD as early as possible. A 5 ms tap is stretched to about 20 ms
  by C27, so whether it turns the board on depends on boot-to-PWR_HOLD time.

### 3. ESD on the edge button: this affects the committed design too (review M2)

The reviewer ran a −8 kV, 150 pF/330 Ω discharge into BTN_N (their scratch
netlist). Results:

- BTN_N goes to −4.4 V and LATCH_G is clamped at −0.82 V by Q5's body diode.
- Q4 and Q8 see VGS of −4.5 V and −3.8 V, inside the CJ2101's ±8 V. That
  refutes the gate-rating fear.
- But about **24 A** peaks through D4b, against the BAV70W's IFSM of 2 A at
  1 µs.
- The board also powers on.

C27 only protects against the positive polarity. **Fix: a bidirectional TVS on
BTN_N**, beside SW2.

### 4. Smaller observations

- A 5 ms tap is stretched to about 20 ms (C27 through R24). With PWR_HOLD
  first thing in main(), real boot-to-latch is about 5–15 ms, so **a tap will
  usually turn the board on**.
- **First connecting the cell** gives the same pulse, since C27 starts empty,
  so a freshly assembled board will usually come up on. Moving C27 to sit
  between LATCH_G and VBATT would prevent that, but loses its ESD role.
- The VBUS node floats to about 0.5 V on battery, through R18's back-feed
  (already documented in circuit.py).

## Rejected: "hold the button while plugging in USB" (VBUS-gated strap)

This doesn't work with a charged cell, because the press powers the board up
from the battery and the bootrom samples before USB ever arrives. It only
helps when the cell is dead.

## Independent review (stronger model, fresh context, 2026-10-24)

| # | sev | finding | resolution |
|---|---|---|---|
| B1 | BLOCKER | hot self-start confirmed with typical parts; leakage calibration checked against both datasheet curves; the two paths add up (no double counting) | open: user decision on D2/D3 |
| M1 | MAJOR | 1.2 MΩ timer vs LVC II ±5 µA; the model drew zero input current | **fixed**: R28 560k / C75 10 µF; `ii` corner added (hot +0.3 µA, cold −0.1 µA); window now 2.1–8.5 s. Spec-max residual risk documented |
| M2 | MAJOR | ESD into BTN_N acts as a press and overstresses D4 | open: add a bidirectional TVS (also for the committed design) |
| M3 | MAJOR | BTN_SENSE polarity flip breaks old firmware | documented as a firmware obligation |
| m1–m3 | MINOR | fire-window UX; tap / cell-connect latches; hot-corner coverage only meaningful for the fix variant | documented |
| N1 | NOTE | "chip alive at 3V3 > 1.8 V" is unphysical (VREG_VIN ≥ 2.7 V) | **fixed** in mcu.lib (2.7 V rising / 2.5 V falling) |
| N2 | NOTE | no BSS138W datasheet in design/datasheets | open: fetch it before adopting |
| N3 | NOTE | charger model's 100k on dead VBUS flattered VBUS by ~15 % | **fixed** (10 MΩ); EN at 85 °C went 2.12 → 2.27 V |
| N4–N6 | NOTE | DSI is ~9× pessimistic hot (headroom for the fix); HYSCMP, switches, .ic/uic and the LDO model checked; the off-state LATCH_G budget is unchanged by the proposal | — |
| N5 | NOTE | RUN double-tap (OTP) could delete Q7 at the cost of an OTP write | noted as an alternative |

## Not modelled

- Flash /CS activity beyond "XIP drives it high".
- The LED rail.
- ESD.
- LVC input leakage beyond the ±0.1–0.3 µA corner. At its 5 µA spec max, any
  µA-level RC timer breaks. Typical is nA.
- The RP2350's real boot timing. picoem (a cycle-accurate RP2350 emulator) runs
  the real bootrom and could pin down t_samp; see the roadmap in docs/PLAN.md.
