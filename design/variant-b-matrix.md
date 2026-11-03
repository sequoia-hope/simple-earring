# Variant B: matrix-driven RGB LEDs (study, 2026-11-03)

User request: an alternate earring that drives plain RGB LEDs from a matrix driver, as
round-pendant does, in place of 45 WS2816C pixels. Same LED count for now, room to add more
later. Drivers on the back, the MCU and small parts on the front. This note covers the
architecture, the fit, the cost and the battery life. No board yet.

## Architecture

The design follows round-pendant (`~/pcb/round-pendant/design/architecture.md`,
`parts/drivers.md`, `parts/leds.md`).

- **Driver:** one Lumissil IS31FL3741A (C2940604), a 9 SW × 39 CS matrix, I²C to 1 MHz, QFN-60
  7 × 7 × 0.80 mm max. It is powered from VSYS, as the ring is today.
  - With 45 LEDs it scans only SW1–SW5 (SWS = 0100, 1/5 duty, ds p.14), using 27 of 39 CS.
  - Growth with no hardware change: 9 SW gives 81 RGB; all 39 CS gives 117.
- **LEDs:** XINGLIGHT XL-1010RGB-YG (C965834), 1 × 1 mm, common anode. They are round-pendant's
  audited part, and smaller than the WS2816C's 1.3 mm.
- **Dimming:** 8-bit PWM per LED × 8-bit scaling per LED × 8-bit global current (GCC).
  - Setting GCC for the earring's dim range puts all 256 PWM steps across the levels actually
    used, so the fine low-brightness steps the WS2816C was chosen for (decisions.md 2026-10-24)
    carry over.
  - Per-LED scaling handles colour balance without spending PWM resolution.
  - PWM runs at 29 kHz, so no visible flicker.
- **What goes:**
  - the three zone switches U4/U9/U10 (TPS22913, WCSP), with R10/R33/R34 and C20/C78/C79;
  - the three level shifters Q3/Q9/Q10, with R23/R31/R32;
  - the 23 LED bypass caps;
  - the VLED_L/R/C nets and their In2 pours.

  The zones existed only because each idle WS2816C draws ~0.7 mA. With a driver, a dark LED
  draws nothing and the whole matrix shuts down to 0.5 µA through SDB.
- **What comes:**
  - **Driver support:** PVCC 2 × (1 µF + 100 nF) + 22 µF bulk; AVCC 1 µF + 100 nF; RISET.
  - **SDB:** 100 kΩ + 100 nF.
  - **INTB:** a 100 kΩ pull-up.
  - **I²C:** a pull-up pair on its own bus (I²C0, 1 MHz with 1 kΩ).

  Net: about 38 parts out and 10 in.
- **GPIO:** this frees LED_DATA_L/R/C and LED_EN_L/R/C (six pins) and uses SDA, SCL, SDB and
  INTB, so two pins come free.

## Fit

Checked against the current placement with the 38 parts removed
(`scratchpad/variantb/fit.kicad_pcb`, `scan_spot.py --art 0.15 --cy-margin 0.1`).

- **The driver does not drop in.** There is no legal 7 × 7 spot on either side as the other
  parts stand.
  - The only free square big enough for its 8.2 mm courtyard is 8.75 mm, directly behind U1.
    U1's nine exposed-pad thermal vias, and the VDD_CORE square vias, come through to the back
    there. Those vias would land in the driver's GND pad, and the VDD_CORE ones would short.
- **A back re-pack looks feasible on area.**
  - Back courtyards cover 275 mm² of ~767 mm² usable, before removals.
  - The driver plus its passives add ~75 mm².
  - That means re-placing the back's small parts (power path, latch, sense dividers) around a
    driver spot, likely at the south or north of the cell area.
  - The front loses 23 bypass caps and gets smaller LEDs, so it decongests.
- **Height.** The QFN is 0.80 mm max, under the LiPo's 1.1 mm cap.
- **Routing is the real risk.**
  - Every LED has its anode on a SW line and three cathodes on CS lines.
  - **Planned mapping:** 9 SW arcs of 5 adjacent LEDs, so the SW nets stay local, and 15 CS
    lines running as a bus round the ring. That is 1/9 duty, still well inside the LED and
    driver limits at the earring's currents.
    - The bus is 15 lines at 0.254 mm pitch, ~3.8 mm wide.
    - Split over In2 and B.Cu, it is ~1.9 mm per layer.
    - In2 is free, because the VLED pours go.
  - **Alternative:** 5 SW × 27 CS, which halves the peak current but makes a 27-line bus.

## Cost (LCSC unit prices at 10 boards, 2026-11-03)

| | per board |
|---|---|
| **Removed:** 45 × WS2816C ($0.0714) | −$3.21 |
| 3 × TPS22913 ($0.41) | −$1.22 |
| 3 × BSS138W, 6 resistors, 3 × 10 µF, 23 × 100 nF | −$0.25 |
| **Added:** IS31FL3741A ($3.31 at 10+) | +$3.31 |
| 45 × XL-1010RGB ($0.0307 at 100+) | +$1.38 |
| ~10 passives | +$0.08 |
| **Net, parts** | **≈ +$0.09** |

- The number of extended parts is about the same: WS2816C and TPS22913 go, the IS31FL3741A and
  XL-1010 come. So JLC's per-order setup fees don't change much.
- Assembly gets easier: three 0.4 mm-pitch WCSP switches go, one QFN-60 comes.
- The PCB is unchanged: same 4-layer outline.
- **Cheaper alternative: IS31FL3733** (C506251, QFN-48 6 × 6, 2370 in stock, $1.53).
  - Saves ~$1.80 per board.
  - Lower draw: 2 mA typ quiescent against 3.6.
  - Smaller, so easier to fit.
  - But it has no per-LED scaling register, always scans all 12 SW (1/12 duty), and tops out at
    60 RGB.

## Battery life (140 mAh LPR302823, ~130 mAh usable; estimates, not measured)

Assumptions:
- MCU + flash + LDO awake at 50 MHz: ~10 mA.
- IMU: ~0.5 mA.
- LED drive at the firmware's dim levels: ~2 mA average, which is the same either way.
- WS2816C idle: 0.7 mA typ (1.0 max) per powered LED, so 31.5 mA for 45.
- IS31FL3741A: 3.6 mA typ while on, 0.5 µA in shutdown.
- Show duty: from the Aug 25 wear log, the share of time the LEDs are on is 25 % standing,
  49 % walking and 82 % dancing. Today's naps exist to cut LED idle current.

| mode | current board (WS2816C) | variant B, same naps | variant B, no naps (always showing) |
|---|---|---|---|
| standing | 18.9 mA → **6.9 h** | 11.9 mA → **10.9 h** | 16.1 mA → **8.1 h** |
| walking | 26.9 mA → **4.8 h** | 13.2 mA → **9.8 h** | 16.1 mA → **8.1 h** |
| dancing | 38 mA → **3.4 h** | 15.1 mA → **8.6 h** | 16.1 mA → **8.1 h** |
| always on, no naps | 44 mA → **3.0 h** | — | 16.1 mA → **8.1 h** |

- **Variant B is 1.6× to 2.7× longer** at the same duty. With the IS31FL3733 (2 mA), the
  always-on case is 14.5 mA → 9.0 h.
- **Off is unchanged.** The soft latch takes everything to zero load either way.
- **The next lever is the MCU,** at ~10 mA, now the largest load. Both LED types hold their
  last frame, so the MCU could sleep between frames on either board. With the matrix,
  always-on could reach roughly 15 h. Firmware, unmeasured.
- **Brightness per mA** is similar but not equal. The WS2816C gives 90/190/25 mcd at its fixed
  ~3.5 mA per channel. The XL-1010's green is roughly 22–40 mcd/mA from its p.6 curve. LED
  drive is the small term here, so this moves the totals by well under 1 mA.

## Next steps

1. Variant plumbing: hw/earring/b, a `[[boards]]` entry in pcbview.toml, VARIANT selection in
   paths.py, and a variant branch in circuit.py and design.yaml.
2. Phase 1: audits for the IS31FL3741A and XL-1010, adapted from round-pendant's, plus the
   matrix map.
3. Phase 2: schematic.
4. Phase 6: back re-pack around the driver.
5. Phase 7: routing.
6. Gates from phase 1 on, for variant B only. Variant A is untouched.
