# BT1 — LiPol LPR302823 cell + two solder pads

**Datasheet:** `design/datasheets/LPR302823.pdf` (LiPol dwg FD_6110_20, 2020-08-17, 1 page). Opened and read 2026-10-22.

## What the board carries

BT1 becomes a **bare-copper footprint** (`BAT_LIPO_PADS`) with no LCSC part. It
is excluded from the JLC BOM/CPL the same way TP1–TP3 are (`lcsc: ~` in
parts.yaml). The cell is hand-soldered and taped after assembly.

| pin | net | what |
|---|---|---|
| 1 | VBATT | red wire (+) |
| 2 | GND | black wire (−) |

## Datasheet facts that constrain the board

| item | datasheet | consequence |
|---|---|---|
| outline | Ø28 ±1.0, flat chord at 23 ±1.0 from far edge | flat sits 9.0 mm from centre (nominal), chord half-width 10.7. Across tolerance the flat sits 7.5–10.5 from centre and the chord half-width reaches 12.4 (Ø29 / flat at 7.5). The fit check uses the full union envelope, not the nominal chord. Worst case Ø29 → r 14.5 against a 15.25 board edge |
| thickness | side view prints "28 ±0.5" — **drawing error** | design to 3.2 (vendor page). Name implies 3.0 |
| leads | wires out of the flat, 50 ±3 mm. Wire gauge **not stated** | pads sized for 28–30 AWG; the cell needs measuring on arrival |
| max charge voltage | 4.35 V ±50 mV | the charger's 4.20 V CV is under it |
| PCM overcharge trip | 4.355 V ±50 mV (min 4.305) | **rules out the LGS4056H-4.35 variant**: a 4.35 V CV could cross the PCM's minimum trip point |
| PCM overdischarge | 2.75 V ±50 mV, resume 2.50 V (charger-detect release, see below) | firmware must shut down well above this. The LDO needs ~3.4 V anyway |
| max charge current | 70 mA | R8 = 18k → 50 mA, see r8-rprog.md |
| max continuous discharge | 140 mA | firmware LED budget (~20 mA avg) is well under it |
| internal impedance | < 200 mΩ | gauge IR correction ≈ 50 mA × 0.2 Ω = 10 mV |
| PCM overcurrent | 2–4.5 A | no board interaction |
| charge temp | 0–45 °C | worn on a body, fine. No NTC, TEMP→GND stays |
| NTC | none | — |
| mass | ~3.0 g | vs RJD2032C1 + clip, similar |

**Overdischarge "resume 2.50 V"** (corrected after gate-1 review): this is
not a typo. DW01-class pouch PCMs release an overdischarge trip by *detecting
a charger*, not by the cell voltage recovering. After a trip the pack
terminals read ~0 V until a charger is applied. The LGS4056H recovers that:
below V_SHORT (0.6 V) it charges at 5% I_CC = 2.5 mA, then trickles at 10%
= 5 mA up to V_TC (2.90 V typ), then goes to CC (LGS4056H ds p.4, table 4).
The datasheet also lists "Discharge Cut Off 2.75 V" as a pack requirement,
so **firmware owns the floor** and must shut down well above it.

**PCM strip:** the flat end (~2 mm) holds the folded seal and the PCM board
and is the pouch's thickest region. The pads sit outside the envelope, clear
of it, and nothing tall may go under that strip.

## Sourcing

lipobattery.us (LiPol Battery), MOQ 5, no LCSC listing (LCSC category 57 holds
no LiPo cells). Hand-fitted part, so the JLC order is unaffected.
