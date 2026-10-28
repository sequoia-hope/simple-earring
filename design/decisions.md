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
  - *(Superseded 2026-10-24: adopted with R27 4.7k, R28 680k, C76/R29
    10n/1M, and Q4 → LBSS84WT1G; see the entries below.)*

## 2026-10-24 — adopted: one-button BOOTSEL, silicon D2/D3, button TVS (user decision)

The user asked "is accidental BOOTSEL temporary or does it erase firmware?" and
was told it is temporary: the bootrom only exposes the drive/PICOBOOT, and
flash changes only if someone writes a UF2. Their decision: **one-button,
silicon D3, BAV99W, TVS**.

- **SW1 deleted; long hold on SW2 = BOOTSEL / force-off.** The `one_button()`
  proposal went into circuit.py as simulated, with these changes:
  - **R28 560k → 680k.** C75 is now the BOM's existing CL10A106KP8NNNC (X5R,
    basic part). Its corner stacks tolerance, X5R temperature and DC bias
    (0.70 hot, 1.10 cold). With 560k, the hot minimum fell under 2 s once
    the bias loss was counted. Window: **2.2–10.3 s, 5 s typical** (2.0–19.4 s at U8's II limit, review F3). The user
    accepted the early end, knowing an accidental trigger only costs a reboot
    (on battery: off on release) or, with USB in, a dark board until unplug.
  - **C77 added** (100n U8 decap).
- **D2 → BAV99W** (Nexperia, C8662). Same SOT-323 series-pair pinout as
  BAT54SW, so the footprint and netlist don't change. The EN clamp loosens
  to VBATT + 0.6 V. That is still legal, because EN is only ever driven to
  VBATT − 0.6 or VBUS/2.
- **D3 → 1N4007WS** (MDD, C193404, SOD-323: the same land, pad 1 = cathode).
  Rejected alternatives:
  - A higher-barrier Schottky: no datasheet in hand showing the leakage we'd
    need.
  - A P-FET ideal diode: more parts and no room.
  - R17 → 22k: simulated, not a fix (EN 1.11 V at 85 °C).

  The cost is VSYS ≈ VBUS − 0.8 V. That is accepted on the grounds that the
  ring's 3.7 V floor is only violated on a ≤ 4.5 V port, and only when the
  LEDs are on.
- **Button ESD: D6 PESD5V0S1BL at the pad, plus R30 1k.** The user approved
  the TVS. R30 was added because a TVS alone does not help the negative
  strike: D4 + Q5's body diode (about 1.4 V) conduct before a 5.5 V-VBR
  TVS does. R30 makes the TVS the only low-impedance path. Simulated:
  ≤ 22 mA reaches BTN_N, and the strike no longer counts as a press.
- **D4 BAV70W: Diodes (C93029, 100 left) → Nexperia BAV70W,115 (C28064,
  17k).** The pinout is the same (Table 2).
- **74LVC2G14: Nexperia GW (C6085, 2.8k stock)** rather than TI. Same
  thresholds, but II is ±1 µA where TI's is ±5 µA, and that matters for a
  µA-level timer.
- **Placement:** see `scripts/place.py` ONEBTN. Q6/R29 went to the FRONT,
  into SW1's old spot. After Q7 took the spot under R3, no back spot near
  RUN would hold a SOT-323. A centre keepout around U1 keeps the back under
  the MCU free for escape vias.
- **Firmware has to change with this board:** GPIO21 is active high with no
  pull-up, and the long-press-off must be under 2 s.

## 2026-10-24 — adoption review fixes; Q4 → LBSS84WT1G (user decision)

- **F2:** the latch's hot off-state margin depended on an unspecified CJ2101
  tempco. With R24 100k and the CJ2101's 0.45 V minimum threshold, EN reached
  0.67 V at 85 °C if the threshold falls 3 mV/°C. Options offered:
  - Q4 → a high-threshold P-FET;
  - R24 → 22k (+140 µA while on);
  - both;
  - accept as is.

  **The user chose Q4 → high-Vth P-FET**: LRC LBSS84WT1G, C383208,
  0.8–2.0 V. Q4 passes only ~30 µA, so its higher RDS(on) costs nothing.
  Q2 and Q8 stay CJ2101 (they need low RDS(on) or don't matter when off).
- **F4:** R27 10k → 4.7k.
- **F5:** C76/R29 100n/100k → 10n/1M.
- **F1:** Q6/R29 moved off the silk art.
- **F7:** D6 moved to C27's spot and C27 moved behind R30. The locked D6-first
  pre-route is left to the user's autorouter as a constraint.
- **F6** (silicon D3 on weak ports, DONE may not assert): accepted. It is
  on the bring-up list.

## 2026-10-24 — LED ring → WS2816C-1313/4P in three zones (user decision)

- **Part:** Worldsemi WS2816C-1313/4P (C42417612, 67k stock).
  - Why: 16-bit per channel plus 4-bit gamma, so the earring's low brightness
    has fine steps; the user's motivation, with the bigger 140 mAh cell.
  - VDD floor is 3.3 V (SK6805: 3.7 V).
  - Costs:
    - idle current 0.7 typ / 1.0 max mA per LED (SK6805: 0.3);
    - operating temperature only −40…+65 °C;
    - MSL 5a;
    - 0.65 mm tall;
    - 2× frame time and a 280 µs reset (firmware).
  - VIH is 0.7·VDD. I first quoted 0.55 from the A-variant survey, which was
    wrong, so the level shifters stay.
  - Footprint: the EasyEDA land (0.50 pads at ±0.40), checked against the
    datasheet drawing. The pin order is the SK6805's rotated 90°, so the
    diamond ring and the k-loop carry over.
  - Fit check: 1.6 mm courtyards clear each other at the tightest LED
    spacing (2.33 mm). Only LED44 forced moves: D3 0.25 mm, C29 0.5 mm. The
    relaxer moved C18 0.15 mm and C26 0.36 mm.
- **Three zones (user chose 3 of 1/2/3/5):**
  - left LED1–18;
  - right LED19–37, chained in REVERSE so data enters at the chevron
    (LED37), beside the left zone's entry;
  - centre LED38–45.
- **Each zone is its own chain + switch + shifter:**
  - U4/U9/U10 TPS22913, with R10/R33/R34 pull-downs and C20/C78/C79.
  - Q3/Q9/Q10 + R23/R31/R32. Each pull-up goes to its own zone rail, so a
    dark zone's first DI is never driven above an unpowered VDD.
  - Rejected: per-zone power on one shared chain. A dark LED breaks the
    chain, and the still-driven DI back-feeds it through its clamp.
- **GPIOs:**
  - Data: GPIO16/17/18 (pins 27–29, adjacent, so one PIO program can clock
    all three chains in parallel).
  - Enables: GPIO1 (L, existing), GPIO0 (R, pin 2), GPIO22 (C, pin 34).
- **In2:**
  - VLED_C is an inner band (r 9.35–10.75) for the octagon.
  - VLED_L / VLED_R split the outer band (r > 11.05) along the line between
    the zone boundaries.
  - The 3V3 disc is unchanged.
- **route.py:** the SK6805-specific freerouting workarounds (C30 via-in-pad,
  LED1-3/LED32-34 VLED vias, C32→C30 link, LED_D3 fragment) are removed.
  The board is routed by the user's own GPU autorouter. `build.py route`
  (freerouting) is no longer the plan.
- **Locking (user request):**
  - The LEDs, J1 and SW2.
  - Also BT1 (cell envelope).
  - Also every part that locked copper or a fixed pour lands on: U1, U2, U5,
    R14, and the reference VREG cluster L1/C11/C12/C13/R13/C22.
  - Everything else may be nudged by the router.
- **Firmware obligations:**
  - Three chains, 48-bit GRB, MSB first, reset ≥ 280 µs.
  - Invert GPIO16/17/18 at the pad (each zone has a Q-inverter).
  - Enable a zone's switch and wait for its rail and the LED's POR (≥ 50 ms
    precedent, charge-indicator memory) before sending data.
  - A dark zone's data line is harmless either way: its pull-up is dead.

## 2026-10-25 — 19 parts moved from the front to the back (room around U1)

User request: "free up some space around the CPU and put more components on
the back while staying under the foam height."

- **Height limit:** the under-cell cap stays at 1.1 mm (brief §11; VHB 4956
  1.5 mm tape). Everything moved is at or under it, using datasheet maximums:
  - U2 LGS4056HDA DFN8 0.8 ("0.8 MAX");
  - U3 NCP730 WDFN6 0.80 (A 0.70–0.80);
  - U7 W25Q16JVUXIQ 0.6 (Winbond §10.1 "USON 2x3x0.6"; datasheet now in
    design/datasheets/W25Q16JV.pdf);
  - U4 TPS22913 0.625;
  - 0603 CL10A106KP8NNNC 0.9;
  - D3 SOD-323 1.10, at the cap.
  `gen_lipo_fit_svg.py` treated an unknown height as 0 mm. It now refuses to
  run when a part under the cell has no HEIGHT entry.
- **Moved:**
  - flash U7 + C25 + R3;
  - charger U2 + C16 + C17 + R8;
  - LDO U3 + C18 + C19;
  - D3, C29, R21, R22, R19, R20;
  - LED_L switch U4 + C20, plus R10 (already on the back, moved from the
    tip to U4).
  Spots and reasons are in place.py `BACK`.
- **Kept on the front:**
  - decaps C1–C9 and C13;
  - the reference VREG cluster (locked);
  - crystal Y1 + C14/C15/R1, to keep the oscillator loop on one layer;
  - Q1/R16/C26, since the light sensor must face out;
  - the inner-ring caps;
  - Q3/R23. The back top-left has no SC-70 spot anywhere near the
    LED_DATA_L → LED1 line (best legal spot was 21 mm of total reach).
- **Placement choices:**
  - U7 sits just south of the QSPI pin row. At rot 180 its near row
    carries SCLK/SD0/SD3 (a via and ~3 mm each). SD1/SD2//CS are on the
    far row and wrap round the body (~6 mm). That holds for either
    row-facing rotation, and keeping SCLK on the near side is the better
    half. *(Corrected after review: the first draft said every QSPI net
    was under 4 mm.)*
  - R3 sits at U7's /CS pin. QSPI_SS is the fast side and keeps a short
    stub; BOOTSEL_SW (slow, behind 1k) carries the distance to Q7.
  - U4 moved west, by the VLED_L outer-band half it feeds. Its LED_EN_L is
    a slow GPIO that crosses from pin 3. The alternative, east beside U9,
    would have run the zone's supply ~12 mm west instead.
  - U3's EN faces R17/D2.
  - The charger, D3, R22 and the R19/R20 tap sit on one short VBUS run
    by C16.
  - R19/R20 keep their pads out of U1's back keepout. The first spot put
    R20 under U1's SE corner, where pins 1–3 escape (review). C18 sits on
    U3's VSYS pin, between U3.6 and U4.A2 (review: it had been 2.5 mm away
    with EN/NC between).
  - The back keepout under U1 (about ±5.6 × −6…5) is kept clear for the
    chip's escape vias.
- **route.py:** these freerouting assists were removed because they were
  measured off the old front spots:
  - CHRG / CHRG_DONE escape vias and U2's locked landing loop;
  - U3's scanned 3V3 via (and the now-unused via-spot helpers);
  - the five QSPI straggler vias;
  - the LED_EN_L channel via.
  U2 is no longer locked, because nothing locked lands on it any more.
- **Thermal note:** the charger now sits under the cell. Dissipation is
  (VBUS − VBAT) × 50 mA ≈ 65 mW typical and 110 mW worst (5.25 V port, 3.0 V
  cell). Plus D3: on USB, all VSYS current (MCU plus every lit LED) goes
  through it, so about 0.85 V × 0.14 A ≈ 0.12 W at the brief's ceiling,
  4.5 mm from U2. The charger's own thermal regulation protects the
  charger, not the pouch. Firmware should cap brightness while charging,
  and D3 / U2's EP get thermal vias to In1 GND. On a 30 mm board, the
  rise is set by the whole board's ~70 K/W to air, not by which side the
  part is on. Bring-up check: cell-surface temperature while charging, with
  the LEDs lit (the LiPo's charge limit is 45 °C).
- **Result:**
  - front parts within r < 10: 40 → 26;
  - front courtyard area within r < 10: 107 → 57 mm²;
  - DRC 0 errors, 274 unconnected (unrouted);
  - no new silk-to-silk overlaps;
  - cell fit: no clash.

## 2026-10-26 — First full route by ultraroute (seed 3 of 6)

- Routed the bb22fb7 placement with ultraroute's locked-copper recipe at its
  working-tree build of 2026-10-26 11:51 (commit a73afa0 plus the uncommitted
  cleanup change). Recipe: `--negotiate --rip-up --nudge --tighten --strip
  --prefanout --shove-plough rip --shove-repair 20 --shove-ties
  --shove-passes 60 --shove-patience 8`, 240 s, 2 threads. Seeds 0–5 left
  2/1/1/0/0/1 open. Lab experiment `earring-reroute-21`.
- Kept seed 3: 321 vias, 1354 mm of track. It adds no DRC warning beyond the
  placed board's, and its only placement change is R16 moving 0.5 mm north
  (now in place.py). Seed 4 was shorter (316 vias, 1287 mm) but put C26's silk
  over the art.
- The rp2350_power group the router job adds was stripped, so the board
  matches what the pipeline makes.
- Project DRC: 0 errors, 0 unconnected, schematic parity 0. 74 warnings, all
  of them silk, library or the locked pre-route vias' dangling flags.
- Open (gate 7 not passed): the USB pair is split. DM goes about 60 mm round
  the east side on In2, and DP about 34 mm round the west side across In1 and
  In2 with 8 vias. 324 mm of signal runs on In1, the GND reference plane. Next
  step is a locked USB pre-route, or diff-pair support in the router.

## 2026-10-27 — Re-routed with In1 kept as a plane (lab earring-planes-in1, P-s1)

- This supersedes the 2026-10-26 seed-3 route, which was never committed.
- First pick was lab `general-57` run `L-s0`:
  - The router was the working-tree build at 5a8428d, with diff pairs and
    power nets that don't neck below their pad's width.
  - The job was `earring-kicad-locked`: bb22fb7 with its locked copper kept.
  - It has the fewest vias of that build's 0-open runs.
  - negotiate2-reg4 ear-s1 was shorter, but it necks VSYS to 0.127 mm for
    2.9 mm.
  - But L-s0 still ran 297 mm of signal on In1, the GND plane, including
    the USB pair.
- easy_pcb's routing flow reserves plane layers with `--planes`, and the
  earring had never been routed that way. Re-ran L-s0's recipe with
  `--planes In1.Cu`, seeds 0-2.
  - The router was the same binary, built 01:03.
  - Recipe: `--negotiate --rip-up --nudge --tighten --prefanout --diff-pairs
    --shove-plough region --shove-reach 0.5 --shove-repair 20 --shove-ties
    --shove-passes 60 --shove-patience 8 --strip --planes In1.Cu --threads 1
    --timeout 240`.
  - Seeds 1 and 2 reached 0 open; seed 0 left VBSENSE open.
- Kept seed 1 (`P-s1`):
  - In1 carries no signal; the GND plane fills as one piece of 690 mm²
    (L-s0: 3 pieces, 582 mm²).
  - USB_DM is 25.1 mm and USB_DP 24.8 mm, 0.3 mm apart, mostly on In2 next
    to that plane. The 10-26 route had 61.5 and 34.1 mm.
  - VSYS's narrowest track is 0.23 mm, for 0.1 mm.
  - 415 vias in all.
- Nudge moved no parts, so R16 stays at bb22fb7's (4.5, 7.6), and the
  place.py edit from the seed-3 route was dropped.
- The rp2350_power group was stripped and the zones refilled.
- Project DRC: 0 errors, 0 unconnected.
  - 77 warnings: silk, library, and 10 dangling items. All 8 dangling vias
    are locked pre-route vias.
  - Schematic parity: no net differences. The 28 parity items are no-connect
    pins and the BOM-exclude flags on BT1/TP1-3, the same 28 as before.
- Button sim (design/sim/button): 54/54 PASS. It builds from circuit.py and
  is independent of the layout.
- Open for review: In2's power pours are cut up more.
  - VLED_R fills 63 mm² (L-s0: 178); VLED_C is in 9 pieces and 3V3 in 8.
  - Every pad still connects, but the VLED nets run on 0.15 mm tracks. If
    the ring's full-white current matters, the VLED net class needs a wider
    track.

## 2026-10-27 (later) — Freerouting assist vias removed; re-routed (lab earring-noassist, N-s3)

- ultraroute reported 8 locked vias standing free in the router input.
  The user's call was to fix it on the earring side.
  - They were freerouting-era assists in route.py: the USB_DM/DP and
    IMU_SDA straggler vias, plus the IMU_SDA/SCL/INT1, SWDIO and SWCLK
    channel vias.
  - Their tracks were never locked, so `--strip` left them floating, and
    the router doesn't join free-standing copper.
  - All 8 are removed from route.py.
- The same pass fixed three more locked items in route.py:
  - USB_C_DP's B.Cu "rise through B6" ran 0.47 mm past the pad and
    dangled; dropped.
  - The VBUS F.Cu trunk's last segment ended at (2.35, -13.45), the old
    spot of the tie via moved on Aug 7. It now ends on the via at
    (2.20, -12.99).
  - R14's 3V3 via-in-pad into an In3 pour now goes in only on 6+ layers.
    On 4 layers there is no In3, and the via dangled.
- The regenerated pre-route board (`route.py --no-freeroute`) differs from
  the bb22fb7 router input by exactly those 11 items. Pre-route DRC: 0
  errors.
- Routed with the P-s1 recipe (`--planes In1.Cu`, 1 thread, 240 s) on the
  ultraroute target-dev build of 02:10 (802cb3a), seeds 0-3.
  - Seeds 0-2 left 2/1/1 open (LIGHT+VSYS / VBUS_SENSE / QSPI_SD2).
  - Kept seed 3 (`N-s3`).
- N-s3:
  - USB_DM and USB_DP are both 21.3 mm, with 4 and 2 vias.
  - In1 carries no signal; the GND plane fills as 1 piece of 694 mm².
  - In2 pours: VLED_R is 1 piece of 78 mm² (P-s1: 3 pieces, 63 mm²);
    VLED_C is 6 pieces of 32 mm²; VLED_L 3 pieces of 114 mm²; 3V3 5
    pieces of 96 mm².
  - VSYS's narrowest track is 0.23 mm, for 2.6 mm. 411 vias in all.
  - No part moved.
  - One 0.127 mm 3V3 router stub on B.Cu at (108.3, 90.3) was deleted.
- Project DRC: 0 errors, 0 unconnected, 0 dangling. The 67 warnings are
  silk and library only.
  - Schematic parity: no net differences (the same benign 28).
  - The button sim is unaffected (circuit.py unchanged; 54/54 earlier
    today).
- Gotcha: `pcbnew.LoadBoard(lab file).Save(out/...)` rewrote
  out/earring.kicad_pro without its rules. DRC then showed about 1100
  rule errors (via diameter, drill). Restore it with
  `git checkout out/earring.kicad_pro` after installing a board.

## 2026-10-27 (later still) — Pour-aware route (lab pours-1, w3-s1)

- ultraroute a5e5a0e added `--pour-cost W`. Crossing another net's pour
  on a non-plane layer costs W times the length inside it.
  - The earring-kicad-locked job now uses `--planes In1.Cu --pour-cost 3`.
  - Its input is the refreshed pre-route board, without the assist vias.
- Installed lab `pours-1` run `w3-s1`: the earlier recipe plus `--planes
  In1.Cu --pour-cost 3 --seed 1`, ultraroute a190e63 working tree.
  - All 9 pours-1 runs routed; w3-s1 is the cost-3 seed with nothing
    dangling.
- Compared with N-s3 (no pour cost):
  - In2 pours total 426 mm², up from 320.
  - VLED_C is 2 pieces of 56 mm² (was 6 pieces of 32); VLED_R is 154 mm²
    (was 78); VLED_L is 116 mm²; 3V3 is 100 mm² in 9 pieces.
  - The cost: 495 vias (was 411), and the GND plane is 666 mm² (was 693),
    still one piece.
  - USB_DM is 23.8 mm and USB_DP 24.2 mm (was 21.3 each).
  - VSYS's narrowest track is 0.23 mm, for 2.7 mm. No part moved.
- Project DRC: 0 errors, 0 unconnected, 0 dangling. The 67 warnings are
  silk and library. Schematic parity: no net differences.
- The button sim is unaffected (circuit.py unchanged).

## 2026-10-27 (evening) — VLED tracks widened to 0.3 mm; re-routed (lab vled-width-1, s0)

- The VLED_L/C/R nets were on the default 0.15 mm class. The In2 pours are
  cut into pieces joined by tracks, so ring current runs on tracks too.
  The largest zone, VLED_R, feeds 19 LEDs.
- New `vled` net class, 0.3 mm, pattern `VLED_*`.
  - It is in `out/earring.kicad_pro` and `scripts/gen_board.py`.
  - `out/earring.kicad_dru` sets a 0.2 mm minimum for the class, so the
    router narrows these tracks no further than that at the 0.5 mm LED pads.
- Routed seeds 0-3 with the pour-aware recipe (`--planes In1.Cu
  --pour-cost 3`) on ultraroute 8c691ec. Seeds 0 and 3 routed completely;
  seeds 1 and 2 left 3 and 2 nets open. Installed s0.
- Two locked 3V3 access vias from route.py, (-5.85,-1.60) and
  (-4.25,-7.55), went unused on F/B: s0 reached the In2 disc without them.
  They touched copper on one layer only, so they were removed from the
  installed board. route.py still places them.
- Compared with w3-s1:
  - VLED tracks are 196 mm at 0.3 mm, plus 3.5 mm necked to 0.23 mm.
  - In2 LED supply pours total 335 mm² (was 326): VLED_C 55 in 4 pieces,
    VLED_L 132, VLED_R 148. 3V3 is 106 mm².
  - GND plane: one piece, 670 mm². Vias: 479 (was 495).
  - USB_DM 24.6 mm, USB_DP 24.5 mm. No part moved.
- Project DRC: 0 errors, 0 unconnected, 0 dangling; 67 silk and library
  warnings. Schematic parity: the 28 known items only (unused pins, BOM
  flags on BT1/TP1-3).
