# simple_earring

Co-designed LED earring: RP2354A + LIR2032 rechargeable coin cell + TBA-C1010 addressable
RGB LEDs around the periphery. 4-layer, JLCPCB rules, all parts from LCSC.

The design is *generated*: edit `design.yaml` (shape, LED count, sizes) and
`scripts/circuit.py` (netlist), then rebuild.

## Pipeline

```
python3 build.py                # full: board -> place -> route -> drc -> render -> export
python3 build.py --to place     # stop after a stage (board|place|route|drc|render|export)
```

Stages (each is also runnable standalone from `scripts/`):

| stage  | script              | what it does                                        |
|--------|---------------------|-----------------------------------------------------|
| board  | `gen_board.py`      | netlist from `circuit.py` -> fresh 4-layer .kicad_pcb, outline, nets |
| place  | `place.py`          | LED ring, MCU cluster front, holder back, USB at edge |
| route  | `route.py`          | scripted LED-ring routes + freerouting for the rest, zone fills |
| drc    | `drc.py`            | kicad-cli DRC, parsed pass/fail report              |
| render | `render.py`         | top/bottom PNG renders into `out/` for review       |
| export | `export.py`         | JLCPCB gerbers/drill + BOM/CPL from LCSC numbers    |

Outputs land in `out/` (`earring.kicad_pcb`, renders, `gerbers/`, `jlcpcb/`).

## Sources of truth

- `design.yaml` — geometry + rules parameters
- `scripts/circuit.py` — components and nets (references `bom/parts.yaml`)
- `bom/parts.yaml` — every part with LCSC number + footprint
- `library/parts.pretty/` — local footprints (proven ones lifted from prior boards)

## Provenance

Footprints and circuit patterns reuse the proven `earring` (RP2040 + LGS4056H + USB-C)
and `rp2350-pendant` (RP2350 QFN-60, 1010 LED ring) projects.
