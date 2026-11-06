# Variant C: AW20198QNR + XL-1615 matrix (2026-11-05)

User request: "for our discrete driver work, see the lower density trapezoidal boards under round-pendant and adopt
that driver chip and the slightly larger led". Those boards are round-pendant's skewed-parallelogram family
(`~/pcb/round-pendant/design/study/parallelogram/README.md`). Its low-density tiers (`p1-66`, `p2-132`) route on 4 layers
with an Awinic AW20198QNR. The study names the XL-1615RGBC-RF as the larger, cheaper LED for those pitches.

Variant C is variant B with those two parts swapped in. B (IS31FL3741A + XL-1010) is left as it was. Everything is
selected by `design.c.yaml` (`python3 build.py --variant c`), through `leds.matrix.driver` and `leds.part`.

## What changed from B

| | B | C |
|---|---|---|
| Driver | IS31FL3741A, QFN-60 7 × 7 × 0.8 | **AW20198QNR**, QFN-40 5 × 5 × 0.55 (`design/parts/aw20198qnr.md`) |
| Matrix | 9 SW × 15 of 39 CS | 9 SW × 15 of 18 CS (same map: 9-line SW bus, CS triplets local) |
| Growth with no new parts | 81 RGB (9 SW) / 117 | 54 RGB at 9 SW (18 CS), 66 at all 11 SW |
| LED | XL-1010RGB, 1.0 × 1.0, anode pad 3 | **XL-1615RGBC-RF**, 1.6 × 1.5, anode pad 2 (`design/parts/xl-1615rgbc.md`) |
| LED angle on the ring | 45° to the tangent | Square to it (`led_angle: 0`); the four beside J1's legs snap to 90° |
| Peak / average per die | 8.09 / 0.80 mA (RISET 47 k) | 8.51 / 0.84 mA (REXT 47 k) |
| Driver quiescent | 3.6 mA | **1.8 mA** |
| Off (standby, VSYS) | 0.5 µA + R36 pull-down needed | 1.3 µA, internal 1 MΩ EN pull-down |
| Support parts | C80–C87, R35–R39 (13) | C80–C83, C86, C87, R35, R38, R39 (9) |
| GPIO | SDA 16, SCL 17, SDB 18, INTB 1 | SDA 16, SCL 17, EN 18; GPIO1 free (no INTB) |
| I²C address | 0x30 | 0x20 (AD0 = AD1 = GND) |
| Layers | 6 (trial) | 4 (the target; not routed yet) |

## Cost (per board, at 10 boards)

- Driver: $3.31 → ~$0.89, so **−$2.4**.
- LEDs: 45 × ($0.031 → ~$0.015), so **−$0.7**.
- Four fewer passives: about −$0.01.
- **Net: about −$3.1 against B, so about −$3.0 against variant A** (B was ≈ +$0.1 over A).
- Both new parts are extended, as their predecessors were. JLC stock: 6,055 drivers, 718,328 LEDs.

## Battery

Against B's corrected table (`variant-b-matrix.md`), the driver draws 1.8 mA less whenever it is active:
- about 0.5 mA less standing, 0.9 walking, 1.5 dancing (same naps);
- 1.85 mA less with no naps, which takes no-naps from 6.5–7.3 h to roughly **7.2–8.1 h**.

The XL-1615's red is weak below ~10 mA. Red/purple shows therefore sit at the top of B's LED-current range, and firmware
should dim with PWM, not SL/GCC. Off stays negligible: 1.3 µA.

## Placement (2026-11-05)

- **Driver spot.** On the back, a 5 × 5 driver fits clear of U1's escape area in one pocket only: the west, x −12.25…−10.75
  (`scan_spot.py --art 0.15 --cy-margin 0.1`, U1 keepout).
  - U11 sits at (−10.75, 0.75), rot 0 back.
  - Its SW side faces the ring (west), and its control side (VCC, EN, I²C, ISET) faces the MCU.
- **Support parts.** Scanned in signal order, 1–3 mm from their pins (place.py `MATRIX_AW`). The exception is the 10 µF
  bulk cap, ~4.5 mm south.
- **Moved parts.** B's moved parts (`MATRIX_MOVED`) keep their B spots.
- **Placed-board DRC:** 0 errors. The warnings are the same as B's (silk crop, J1 and LED library-mismatch flags).
- **Not done yet:** gate 6 review, routing (gate 7), and a 3D model for the XL-1615 (pcbview shows bare pads).
