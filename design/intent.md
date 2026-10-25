# Design intent — LiPo power source (replaces the coin cell on rev 2)

*Phase 0. Drafted 2026-10-22. **Signed off by the user 2026-10-22**, with R8 = 18k (50 mA) chosen.*

This is a delta on rev 2 as described in `docs/PLAN.md` (commit `4538da2`). Everything not named here — MCU, flash,
LED ring, IMU, light sensor, USB, the VBUS/VSYS/VBATT power path, 4-layer
stackup, outline — is unchanged and keeps its existing intent.

## Purpose

Replace the RJD2032C1 coin cell and its MY-2032-12-R retainer (BT1) with a
round lithium-polymer pouch cell taped to the back of the board and wired to
two solder pads. Goals, in order:

1. **More capacity.** 140 mAh against 85 mAh. *Correction 2026-10-22:* this line
   first said "in less height, against a 5.3 mm stack". 5.3 is `gen_case.py`'s
   unmeasured default, sized for the old QIJEY clip model. The rev-2 coin stack is
   ~3.8 mm (a 3.6 mm RJD2032C1 resting on the board inside a 3.70 mm
   MY-2032-12-R). The LiPo stack is **~4.4 mm** (see Mechanical), so this is a
   capacity win at a ~0.6 mm height cost, not a height win.
2. **Retire the BT1 copper.** The Ø8 centre GND pad and its six mask-defined
   solder bumps go away, and the back centre becomes ordinary routable area. That
   pad causes rev 2's 5 unconnected nets (see PLAN.md); removing it should fix
   them.
3. Keep the change on main. The coin-cell rev 2 survives only in git history
   (user decision 2026-10-22).

Open source, personal board. Same as before.

## The cell — LiPol Battery LPR302823 (hand-fitted, not in the JLC BOM)

From `design/datasheets/LPR302823.pdf` (LiPol dwg FD_6110_20, 2020-08-17):

| | value |
|---|---|
| outline | round Ø28 ±1.0, one flat; flat-to-far-edge 23 ±1.0 (the flat chord sits 9 mm from centre) |
| thickness | **3.0 nominal (part name) / 3.2 (vendor product page)**. The drawing's side-view dimension reads "28 ±0.5", which is a drawing error. **Design for 3.2 and measure the real cell.** |
| leads | wires out of the flat, 50 ±3 mm, through the PCM (PCM sits inside the flat end) |
| capacity | 140 mAh min / 145 typ |
| chemistry | **3.8 V "high-voltage" LiPo**: operating 2.75–4.35 V, max charge 4.35 V |
| max charge current | **70 mA** |
| max continuous discharge | 140 mA |
| internal impedance | < 200 mΩ |
| PCM | overcharge 4.355 V, overdischarge **2.75 V**, overcurrent 2–4.5 A |
| charge temp | 0 to +45 °C |
| mass | ~3.0 g |
| source | lipobattery.us, MOQ 5, not on LCSC |

## Requirements

### Power

- **Cell connection:** two solder pads on the back, `+` and `−`, labelled in
  copper/silk and placed where the wires leave the cell's flat. No connector.
- **Orientation:** the flat faces the USB tip. That is the only orientation
  where a Ø28 outline clears both J1 and the board edge. With the flat at 9 mm
  toward the tip, the outline stays ~3.9 mm short of J1's body.
- **Charge voltage stays at 4.2 V** (the LGS4056H's fixed CV point). This is
  safe for a 4.35 V cell and costs some capacity. The datasheet gives no 4.2 V
  capacity figure; the rough HV-LiPo rule of thumb is ~85–90%, so about 120 mAh
  usable. **Unverified**, to be measured on the bench.
- **Charge current: 50 mA, with R_PROG (R8) going from 22k to 18k** (user
  decision). 900/18k = 50 mA (0.36C), which leaves 29% headroom under the
  cell's 70 mA maximum. See `parts/r8-rprog.md`.
- **Discharge:** the firmware averages ~20 mA (GLOBAL_BRIGHTNESS 8). Any
  sustained LED pattern must stay ≤ 140 mA total, and that becomes a firmware
  constraint to document. The PCM's 2 A trip never matters here.
- **Low-voltage floor:** the PCM disconnects at 2.75 V. The 3V3 LDO needs VSYS
  ≳ 3.4 V to regulate, so the firmware still decides when to shut down, and the
  gauge window moves from 3.0–4.2 V to the LiPo curve. That is firmware work,
  listed below, with no hardware change.
- **(Superseded 2026-10-24, see the addendum below.) The SK6805 3.7 V floor is unchanged.** On battery the ring is only within
  spec above ~3.7 V, the same as before. USB-powered operation still fixes it.
  *(2026-10-24, user decision: the ring is now WS2816C-1313/4P, 16-bit, with a
  3.3 V floor, in three switched zones (left / right / centre). Idle current
  rises to 0.7–1.0 mA per LED, and only powered zones pay it. Operating
  temperature is limited to 65 °C. See decisions.md.)*
- **The power path (D3/Q2, VBATT/VSYS split, R19/R20 load-bearing for Q2) is
  unchanged.** VBATT is still "the cell node only".
- **Power control: momentary button + CPU-held latch** (user decision
  2026-10-22, replacing the SW2 slide switch, which the cell covers at every
  legal angle). A press wakes the CPU, the CPU latches power on, and a long
  press turns it off, with power dropping when the button is released.
  Off-state drain is ~0 by construction. Circuit and leakage budget are in
  `decisions.md`.
- **Button location:** a side-push tact on the tip's straight edge, beside J1
  (the SW2 side), actuated from the edge.

### Mechanical

- Cell sits on the back over the round body, attached with double-sided foam
  tape. Target stack from the back copper to the cell's top (cell
  3.2 + 1.5 tape = **4.7**, against ~3.8 for the rev-2 coin cell + clip).
  *Revised after gate-4 review:* the tape is 3M VHB 4956, 1.5 mm, because
  foam compresses 30–50% at fitting and 1.2 mm left no real margin over
  1.1 mm parts. That puts the target at ≤ 4.8 mm.
- **Parts under the cell outline must be flat.** No part taller than the
  foam-tape thickness may sit under the cell, and nothing with a sharp edge may
  press into the pouch. The exact height cap and tape product get decided in
  the phase-4 brief. Today the IMU (0.86 mm), the SOT-323s Q2/D2 (1.1 mm max) and
  SW2 (1.4 mm) all sit under where the cell will go, so the back placement
  changes.
- The power button's actuator is reachable at the tip edge. J1 stays where
  it is.
- The TPU case (`gen_case.py`) needs a new rear cup for the shorter, wider-flat
  stack. That is a follow-on task, not in this change.

### Manufacturing

- JLCPCB 4-layer, two-sided SMT, as before. BT1 leaves the JLC BOM. The cell is
  hand-soldered to the pads and taped down after assembly.
- **Hand-assembly step added:** solder the two wires, then tape the cell down.
  The wires are 50 mm long and get trimmed to length.

### Firmware follow-ons (not part of this hardware change, tracked here)

- **Power latch (new, required for the board to stay on):** drive GPIO20
  PWR_HOLD high as the **first line of setup()** (users hold the button
  ≥250 ms). Read GPIO21 BTN_SENSE (pull-up, low = pressed, ~0.6 V through
  the BAV70W). Debounce, and ignore the power-on press until it's
  released. Long press → drop PWR_HOLD. **Enable the watchdog:** any reset
  drops GPIO20, so a hang powers the board off instead of draining the
  cell. Auto-off at ≥3.0 V (NCP730 is in dropout below ~3 V).

- `chargePct` / gauge: LiPo discharge curve, 4.2 V full, IR correction ≤ 200 mΩ
  × charge current (≈ 10 mV).
- Shutdown threshold above the LDO dropout and the 2.75 V PCM cut.
- Power-budget comment at the top of `main.cpp`: about 120 mAh usable.

## Explicit "don't care"

- Cell swap without soldering. Not required, which is why there's no connector.
- NTC / thermal charge qualification. The cell has none, and the LGS4056H's
  TEMP pin stays tied to GND as today.

## Known risks / open questions

1. **Cell thickness 3.0 vs 3.2**: measure on arrival.
2. **4.2 V capacity of a 4.35 V cell**: measure on the bench.
3. **Placement churn**: moving the back-side parts out from under the cell, or
   capping their height, re-opens placement and routing. That means a full
   re-place and re-route (the last route took ~2.5 h per attempt).
4. **Wire strain relief**: no through-hole is possible (the front is fully
   populated). The wires rely on tape or kapton over the pads.
