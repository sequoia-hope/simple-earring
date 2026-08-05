# 4-layer partial — 8 nets left to hand-route

`out/earring.kicad_pcb` (committed) is the best of 6 auto-routing attempts on
the 4-layer stackup: **0 DRC errors, 8 unconnected**. Zones are filled, no
lock file. Everything else — 122 parts, 332 nets, the LED chain, the planes,
the USB pair, the VREG cluster — is routed and clean.

Attempts scored 9 / 8 / 11 / 8 / 11 / 11 unconnected. It plateaus; it does not
converge. The remaining 8 are yours.

## The list (longest span first)

| net | from | to | span | note |
|---|---|---|---|---|
| `LED_EN` | R10.1 (back) | U4.B2 (front) | 10.9mm | back-to-front, full board height |
| `IMU_INT1` | U1.12 (front) | U6.4 (back) | 10.0mm | MCU to the back-east IMU pocket |
| `QSPI_SD1` | U7.2 (front) | U1.59 (front) | 9.8mm | flash → MCU, west-to-south |
| `QSPI_SCLK` | U7.6 (front) | U1.56 (front) | 9.0mm | same corridor |
| `QSPI_SD0` | U7.5 (front) | U1.57 (front) | 8.9mm | same corridor |
| `USB_DP` | U1.52 | R6.2 | 4.2mm | pin-51/52 escape to the series Rs |
| `USB_DM` | U1.51 | R7.2 | 3.9mm | same |
| `XIN` | U1.21 | C14.1 | 2.0mm | crystal load cap, short hop |

Exact endpoints are in `out/earring-best.json` (`unconnected_edges`), in
board-center-relative mm.

## What's actually blocking them

Three clusters, not eight independent problems:

1. **The QSPI trio** (SD0/SD1/SCLK) is new in this revision. U7 sits in the
   pocket west of the C3/C5 decap column; its bus has to reach U1 pins 55-59
   on the chip's *south* edge. On 6 layers that run would drop to In3. On 4
   layers there is no In3, so all three want the same F.Cu corridor south of
   the MCU — the one the VREG cluster and the USB series Rs already own.
   SD2/SD3 got through; these three didn't. Moving U7 (or accepting a B.Cu
   detour around the clip's west flank) is the lever.
2. **The two back-to-front signals** (`LED_EN`, `IMU_INT1`) previously used
   the In3 signal layer to cross the board. They now need a B.Cu path that
   dodges the battery clip's 20.8mm courtyard and the locked USB rails.
3. **`USB_DM`/`USB_DP`/`XIN`** are short and local — congestion, not
   topology. `XIN` is 2mm.

## Ground rules if you re-run the generator afterwards

**Your copper becomes the source of truth once you finish it.** `python3
build.py` regenerates `out/earring.kicad_pcb` from scratch and will destroy
hand routing. Same rule as the USB/VBUS edits from Aug 5 (commit `664bcd5`).
To iterate on placement without losing your work, either back-port the change
into `scripts/place.py` / `scripts/route.py`, or lock your tracks and add them
to `route.py`'s pre-route set.

Recover any committed version with:

```
git show <commit>:out/earring.kicad_pcb > /tmp/recovered.kicad_pcb
```

## Review surface

`cd out && python3 -m http.server 8618` — the dashboard shows the 2x2 copper
grid (4 layers now, it adapts to the stackup), both renders and the 3D view.
`out/earring.kicad_sch` is the new generated schematic if you want the
netlist in readable form while routing.

## Fallback

The 6-layer stackup is one line away: set `board.layers: 6` in `design.yaml`
and rebuild (route.py, finish.py, render.py and export.py all switch on it).
6-layer converged fully on the *previous* netlist; it has not been tried with
the QSPI flash added, and it costs JLC lead time — which is why we didn't.
