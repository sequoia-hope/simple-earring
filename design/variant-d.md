# Variant D: variant C with the driver moved off the LED rings

**Parent:** variant C (`design/variant-c.md`): AW20198QNR, 45 × XL-1615, 9 SW × 15 CS, 4 layers.
**Overlay:** `design.d.yaml` (`leds.matrix.spot: tip`, `arc_triplet`). **Board:** `hw/earring/d/`.
**Why:** the user's call (2026-11-06). Keep the LEDs, the centred MCU, the button and USB where they are; move the driver
anywhere, clear of the LEDs. In C it sat on the back directly under LEDs 8–10 and inner LED39.

## Where the driver can go

Each LED is on the front and needs through-vias beside it. So I took every LED courtyard plus a 0.3–0.7 mm margin as a
keepout on the back too, then scanned a 5.8 mm square courtyard at every 5° rotation. Two other keepouts applied: U1's
back escape keepout (±5.6 × −6…5) and J1.

- **Only one spot fits:** the pocket south of J1 and north of U1, at about (−1.75…1.0, −9.5).
- **No room to clear every part off the LEDs.** The back's free area off the LEDs is ~203 mm². The movable back parts'
  courtyards total ~277 mm².
- **Under U1 is out:** on variant A's routed board, the keepout is full of escape vias.

## Placement (place.py `MATRIX_AW_TIP`, `TIP_MOVED`; scan_spot in signal order, LED keepouts on)

- **U11** at (0.00, −9.25), rot 270, back.
  - The SW side faces north toward J1 and the free In2 band. CS1–9 face west, CS10–15 face east.
  - The control pins face south. EN/SCL/SDA sit ~3 mm from U1 pins 27–29.
- **Support parts:**
  - C81/C80 (PVCC) go on the front, over pin 5, 1.2/2.4 mm away. J1's courtyard leaves no back spot north of the chip.
  - C83 is on the back at the SE corner. C82 is on the front.
  - R35 (ISET) is on the back at the SW corner.
  - R39, R38 and C87 are on the front, between the driver and U1.
  - C86 (bulk) is on the front, 3.9 mm away.
- **Parts evicted from the pocket:**
  - U5 (USB ESD) moved to the front at the tip, on the USB_C_DP/DN front joins (no back spot near J1 was left).
  - R7/R6 moved to the front by U1's USB pins (they're series terminations at the MCU end).
  - C28 went beside the J1 VBUS via. U5's VBUS via, stub and trunk pre-routes are off for this variant (route.py).
  - The BOOTSEL timer moved:
    - Q8 to U1's west edge on the back.
    - R26 to the front.
    - U8 to the front, east of U1.
    - C75 and D5 to the back east.
    - R28 to the front.
- **Placed DRC:** 0 errors after route.py's refill. Schematic: 77 nets verified.

## Routing on 4 layers (ultraroute 99bb7ca, recipe args, `--planes In1.Cu`, 6 seeds × 900 s, KiCad-judged)

| Trial | Open | DRC err | In1 GND |
|---|---|---|---|
| C (driver under the ring), for reference | 37–45 | 0–2 | 610 mm² |
| D, driver in the tip pocket | 41–50 | 1–4 | ~610 |
| D + `arc_triplet [1,2,5,4,3]` (each driver side serves its own half of the ring) | 43–50 | 1–4 | ~610 |
| D + remap + `matrix` netclass 0.10 / 0.10 mm for SW?/CS?/CS?? (`hw/earring/d/earring.kicad_pro`) | **28–37** | 1–2 | 601–612 |

- **Moving the driver alone changed nothing.** The opens left the driver's pins and spread out. With 0.10 mm matrix
  rules they are ~12–18 matrix connections (SW and CS about equal) plus ~15–20 other nets. These are mostly MCU
  signals and power round the board edge: USB, SWD, IMU, BOOTSEL, VSYS/VBATT.
- **The board is capacity-bound on 4 layers with In1 kept whole.** The matrix adds 180 LED pins to what variant A
  routed. The remaining levers:
  1. **6 layers.** B got 8–10 open on 6, with the driver under the ring.
  2. **0.10 / 0.10 mm for every signal class,** not just the matrix. JLC's 4-layer standard is 0.09 mm, and
     round-pendant's p1-66 routed 100 % on 4 layers this way.
  3. **Unload the back:** fewer or smaller back parts under the LEDs (TP1–TP3 are 2.5 mm pads).
- **The 0.1 mm class:** CS lines carry 8.5 mA and SW lines 128 mA pulses. 0.1 mm is ample on 1 oz outer and 0.5 oz
  inner copper (IPC-2221, ΔT 10 °C: ~0.2 A inner).
