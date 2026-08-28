# TPU clip-on case

Two-piece flexible case for the **ordered** earring revision (commit `43eadc1`).
Generated, not hand-modelled:

```
python3 scripts/gen_case.py            # -> out/case/*.step, *.stl, report.txt
python3 scripts/gen_case.py --bat 4.5  # if the real battery stack differs
python3 scripts/preview_case.py        # -> out/case/preview/  (served on :8618)
```

`gen_case.py` needs **cadquery** (OCC kernel), which the system python does not
have — `python3 -m venv ~/.venvs/cq && ~/.venvs/cq/bin/pip install cadquery`,
then run it with that interpreter. `preview_case.py` is numpy-only and runs on
the system python.

`gen_case.py` reads the board straight out of git (`git show 43eadc1:out/earring.kicad_pcb`)
— outline, all 45 LED positions, every courtyard — so the case tracks the
hardware rather than a copy of its numbers. The working tree is on rev 2, which
is *not* the board that exists.

## The two halves

**Front — diffuser.** A dish with a flat outer face at z = +3.45. The inner
floor sits at +1.05 over the LED ring and +1.60 over the MCU cluster; each of
the 45 LEDs gets its own tapered pocket bored up from +1.05 to +2.35 (Ø2.0 at
the mouth, Ø1.24 at the ceiling), leaving 1.10 mm of TPU between the pocket and
the smooth outside. The eight interior LEDs sit on Ø3.4 bosses that bring their
local floor back down to +1.05, so all 45 pockets are optically identical. The
webs between adjacent ring pockets are ~0.5 mm at the mouth and thicken going
up, so the ring reads as 45 bright nodes joined by a fainter glow.

SW1 (BOOTSEL, 2.55 mm tall — the tallest thing on the front by 1.5 mm) is not
cut through: the cover thins to a **0.70 mm membrane** over it, so it stays
pressable through the case.

**Rear — battery cup.** A closed cup, flat outer face at z = −8.45, 1.20 mm
floor and outer wall, interior open from −7.25 up to the board. The coin cell
and its clip live entirely inside it; nothing conductive on the back is
reachable. A Ø13 pad on the cup floor stands 0.10 mm proud of the cell so the
cell is lightly backed up rather than rattling.

## How they clip on

The rim is divided into **stations** that alternate FRONT / REAR ownership. At
its own stations a half sends a **finger** (1.7 mm thick, 4.0 mm wide) past the
board mid-plane, wraps the PCB edge, and catches a flat lip on the *opposite*
board face — 1.00 mm onto the back for front fingers, 0.80 mm onto the front for
rear fingers. So **each half clips to the PCB by itself**.

At the same station the mating half is simply cut away through the full wall,
so the two rims interleave as a plain castellation. **There is no half-to-half
catch and nothing protrudes** — the castellation only keeps the halves aligned
and closes the seam; all the retention is each half's own grip on the PCB. The
fingers fill the wall (1.70 mm), so the outer surface stays flush and the seam
reads as an alternating band. Both halves carry the identical pattern, offset
by one station.

Stations (CAD degrees, +y = the USB tip):

| station | 195 | 232 | 252 | 272 | 292 | 312 | 332 | 25 | tipL / tipR |
|---|---|---|---|---|---|---|---|---|---|
| owner | rear | front | rear | front | rear | front | rear | front | front |

Front stations wrap onto the **back** face, so they are placed only where the
back is clear near the edge — the battery clip arms reach to r 14.1 at ±x and
the test points crowd the left flank. Rear stations wrap onto the **front**
face, where the only obstacle is the LED ring at a uniform 1.22 mm in. The two
`tip*` hooks on the straight flanks are front-only (the rear rim has already
stepped down there) and hold the tip flap of the diffuser.

`gen_case.py` measures every lip against the real courtyards and prints the
margin; nothing is assumed.

## Openings

- **USB-C — this is also the mount.** The earring hangs from a loop soldered
  to a male plug that stays in J1, so the tip aperture is structural, not just
  for charging. Both rims stop short of it: the rear cup is clipped at y = 14.6
  (the connector body starts at 14.33), the front rim ends at y = 19, and only
  the 1.05 mm-thick diffuser flap continues to y = 21 — **0.68 mm short of the
  connector's mating face at 21.68**. Below z = +1.05 the tip is completely
  open, and a 14 × 8 mm plug corridor is verified clear of both halves.
- **SW2 power switch — a thumb scoop.** The knob already sticks 1.25 mm past
  the board edge, and it slides *along* the left flank, so the affordance is an
  open scallop bitten out of **both** rims there: 11.6 mm along the rim
  (y +5.5 up to where the left tip hook starts at +15.3), floor at z = −4.60,
  ceiling at the diffuser's underside — a **5.65 mm tall opening** with the knob
  standing in the middle of it. The lower end is raked back 3 mm at the floor so
  it prints without support and reads as a scoop rather than a slot. The cup
  wall below −4.60 is continuous, and the cell is 5.4 mm further inboard, so
  the battery stays enclosed.
- Everything else on the back stays covered.

## Printing

Both halves print **outer face flat on the bed with no supports** — that is the
whole reason the outer faces are flat and the perimeter roll-over is a 54°
chamfer rather than a fillet. Every cavity (LED pockets, cup interior, station
slots) opens upward. Use `*-print.stl`, which is already in that orientation
with the bed at z = 0.

The only unsupported features are the clip-lip faces themselves: 6 × ~1.0 mm
cantilevers on the front (25.9 mm² total), 4 × ~0.9 mm on the rear (14.1 mm²).
That is one flat lip per finger and it bridges fine; a little droop there only
improves the grip.

| | |
|---|---|
| material | TPU ~95A (translucent / natural for the front) |
| nozzle | 0.4 mm |
| layer | 0.15 mm (0.12 for a smoother diffuser skin) |
| walls | 3 |
| infill | 40–100 % — the parts are mostly wall anyway |
| supports | none |
| bed contact | front 901 mm², rear 805 mm² — no brim needed |
| material | front 2.4 cm³, rear 1.9 cm³ |

## Assembly

1. Front half onto the board first: line up the tip flap, press the six fingers
   over the edge until the lips snap onto the back face.
2. Rear cup on second: its four fingers drop into the front half's castellation
   gaps and catch the front face.
3. To open, peel any finger outward — each half comes off the board on its own.

Assembled: **34.2 × 38.2 × 12.1 mm**. The board itself plus the coin cell is
already 6.9 mm of that.

## Known gap

`--bat` defaults to **5.30 mm** — the QIJEY `BAT_CR2032_W` 3D model (5.10 mm)
that the ordered board shipped with, plus 200 µm. If the clip actually fitted is
the `MY-2032-12-R` (3.70 mm model) or its feet were flattened, the real stack is
smaller and the case can lose up to ~1 mm of thickness; measure the built board
and re-run with `--bat`. It is the only number here that isn't taken from the
board file.

The case adds no hanging point, and doesn't need one: the earring hangs from a
loop soldered to a male USB-C plug that lives in J1. The ordered board has no
ear-wire hole (`b3bea65` added one, a later revision removed it).
