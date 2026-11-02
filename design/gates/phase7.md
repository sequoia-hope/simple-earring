# Gate 7 — routing (rev 3, ultraroute lab vled-width-1 s0)

*2026-10-31. Board: `hw/earring/a/earring.kicad_pcb` as committed at 3be5391. That is the
route installed at 7a83b33, with two unused 3V3 vias removed at bcba710. Router: ultraroute
8c691ec (lab, dirty), recipe `route/earring/recipe.json`.*

**Verdict: FAILED.** DRC is clean, but the battery path runs through two copper necks
below the fab minimum. They are router artefacts that KiCad's default rules don't check
(B1, B2). Required fixes are listed at the end.

## Checks

| check | evidence | ok |
|---|---|---|
| DRC | `kicad-cli pcb drc --schematic-parity --severity-all`: **0 errors, 0 unconnected**. 67 warnings: 34 silk_overlap, 23 silk_over_copper, 5 text_height, 3 lib_footprint_mismatch, 2 silk_edge_clearance | yes |
| schematic parity | 28 items, all benign: 24 `net_conflict` on no-connect pins that carry `unconnected-(…)` names (U1 spare GPIO 2–5/7/9/10/12–15/23–25, J1 SBU1/2, U3 NC, U6 INT2/NC, LED18/19/45 DO = the three zone chain ends) and 4 BOM-exclusion flags (BT1, TP1–3) | yes |
| copper connection width | Scratch copy with `(constraint connection_width (min 0.09mm))` added (0.09 = JLC 4-layer minimum trace). **21 hits.** Real necks: VBATT In2 (98.68,88.08) **0.051 mm**; VBATT In2 (107.3,108.35) **0.077 mm**; CHRG F.Cu (101.33,110.83) **0.051 mm**; 3V3 B.Cu (109.78,88.54) 0.054 mm (on a dead stub); VLED_C In2 pour sliver 0.072 mm. The other 16 are same-net 0.4 mm via lands 0.403 mm apart touching on unconnected layers (benign) | **no** |
| router joints | `tools/route_audit/necks.py`: **81 overlap-only joints** (track ends 0.05–0.28 mm apart, joined only where the round ends overlap). ultraroute's input board for this run (`ultraroute-lab/experiments/vled-width-1/s0/input.kicad_pcb`) has **0** and its `out.kicad_pcb` has 81, so the router makes them | **no** |
| current capacity | `tools/route_audit/power_paths.py` (track cost = whole length, an upper bound; 1 oz outer / 0.5 oz inner). Table below | **no** (VBATT) |
| plane integrity | In1.Cu GND: one piece, 671 mm², no tracks on In1. Its only gaps are two deliberate keepouts under the VREG block (97.4–98.2 × 102.6–105.65, 96.65–99.35 × 105.65–108.0). USB_DM crosses 0.24 mm of one keepout (m1) | yes, m1 |
| USB pair | USB_DP 24.5 mm / USB_DM 24.6 mm, 2 vias each, mostly In2 over In1 GND | yes |
| crystal | XIN 4.9 mm with 2 vias, XOUT 1.8 mm with 2 vias, both through In2 under Y1, beside USB_DM (M2) | **no** |
| decoupling vias | 53 of 55 capacitors have a GND via within 1.0 mm of their GND pad. C74 (1.32 mm, F side) and C25 (1.22 mm, B side) also sit in an outer GND pour | yes |
| VLED width rule | VLED_L/C/R narrowest 0.23 mm (rule min 0.2), 196 mm at 0.3 mm | yes |
| renders | `design/renders/` (skill `render.py`, 2026-10-31): F/In1/In2/B.Cu, top, bottom, 3D. Looked at by the author and the reviewer | — |

### Power paths

| path | R (mΩ) | track mm | narrowest | vias | copper |
|---|---|---|---|---|---|
| VBATT BT1.1 → Q2.3 | 289 | 54.6 | 0.127 | 8 | In2@0.15 29.6, B@0.15 23.9, In2@0.127 1.1 |
| VBATT BT1.1 → U2.5 | 272 | 52.3 | 0.127 | 8 | In2@0.15 27.9, B@0.15 23.9 |
| VBUS J1.B4A9 → D3.2 | 69 | 33.0 | 0.4 | 6 | In2@0.4 17.5, B@0.4 15.5 |
| VBUS J1.A4B9 → U2.4 | 95 | 43.1 | 0.15 | 11 | mostly 0.4; 2.1 mm F@0.15 is a parallel feed |
| VSYS Q2.2 → U9.A2 / U10.A2 / U4.A2 / U3.6 | 26 / 41 / 52 / 48 | 10–24 | 0.23 | 5–10 | 0.4 trunk, 0.23 at the switch pads |

VBATT is not in the `power` net class (`gen_board.py` assigns only VBUS and VSYS), so it
routed at the 0.15 mm default. BT1 and Q2 are 24 mm apart, but the route goes round the
left and bottom edges.

### Warnings explained

- **silk_overlap 34, silk_over_copper 23, text_height 5, silk_edge_clearance 2:** gate 9.
  The 5 text_height hits are the 0.8 mm art text. The 2 silk_edge_clearance hits are J1's
  outline over the edge.
- **lib_footprint_mismatch C38, LED20:** the board copies store pad orientation 360° where
  the library has 0°, and the graphics serialise differently. Pads are the same.
- **lib_footprint_mismatch J1:** a known board-local edit (shortened pads, PLAN.md). The
  reviewer also found its pegs differ from a library copy (N2). The board copy matches the
  ordered rev.

## Review: independent (stronger model, fresh context), 2026-10-31

The reviewer re-derived the numbers with its own pcbnew/shapely scripts and agreed with the
evidence scripts.

| # | sev | finding | resolution |
|---|---|---|---|
| B1 | BLOCKER | VBATT In2 (98.68,88.08): ends 0.141 mm apart, neck 0.050 mm. With it cut, **BT1 reaches neither Q2 nor U2**: it is the only path for all cell current. Below the 0.09 mm fab minimum; it could etch open (dead battery, nothing visible). At 140 mA, IPC-2221 gives ΔT ≈ 33 °C at the neck | open: re-route |
| B2 | BLOCKER | VBATT In2 (107.3,108.35): 0.127 mm onto 0.15 mm, ends 0.124 mm apart, neck ~0.06–0.077 mm. Cut, BT1 → Q2 opens: **the board charges but never runs from the cell** | open: re-route |
| M1 | MAJOR | The joint artefacts are systemic (81) and the project DRC can't see them. CHRG F.Cu (101.33,110.83) 0.051 mm is the only path U2.7 → U1 (charge status silently dead). The 3V3 B.Cu neck and the VLED_C sliver are cosmetic or CAM flags | open: permanent `connection_width` rule + ultraroute fix (below) |
| M2 | MAJOR | XIN/XOUT on In2 with 2 vias each, under Y1, 0.26 mm from USB_DM for ~1 mm. Y1, C14, C15, R1 and U1 are all on F.Cu within 3 mm: route XIN round Y1 pad 4's east edge on F.Cu, XOUT straight | open: pre-route on F.Cu, locked (skill routing.md step 4a) |
| M3 | MAJOR | VBATT goes 54.6 mm round the edge for 24 mm direct, at 0.15 mm, Default class. ~0.28 Ω. That is 39 mV at 140 mA: within the requirement, and 0.127 mm inner is good for 0.16 A at ΔT 10 °C. Not a capacity failure, but the ugliest route on the board, ~1 % gauge error, and where B1/B2 live | open: VBATT → `power` class, plus a `track_width` min rule (LESSONS) |
| m1 | MINOR | USB_DM In2 (97.60,101.03)→(98.83,104.73) has 0.24 mm inside the In1 VREG keepout | with the re-route; see N1 |
| m2 | MINOR | VDD_CORE: C6 reaches U1 pin 6 via 3.3 mm of 0.127 mm In2 and 2 vias, though it sits 1.4 mm away. C5 takes ~4.3 mm of F.Cu. VREG_LX itself is good (F.Cu only, 3.2 mm + pour) | with the re-route |
| m3 | MINOR | On USB with no firmware cap, full white ≈ 565 mA of LEDs + MCU ≈ 0.62 A on VSYS. The 0.4 mm In2 trunk then sees ΔT ≈ 32 °C (0.37 A at 10 °C). VLED copper is fine (0.3 mm: ~6 °C). Fine if the 140 mA firmware cap also applies on USB; otherwise widen the VSYS trunk to 0.5–0.6 mm | decide with the re-route; D3's ~0.6 W at that current is a separate power question |
| m4 | MINOR | 9 dangling stubs: 3V3 F.Cu (97.0,102.29) (103.01,102.22) (97.28,96.49); 3V3 B.Cu (109.6,88.56); BTN_SENSE B.Cu (95.98,91.18); VBUS_SENSE B.Cu (107.73,101.18); LIGHT F.Cu (102.83,106.03); VBATT B.Cu (105.93,84.88); VLED_R In2 (109.58,98.58) | strip in the route stage |
| m5 | MINOR | USB_C_DP: a needless 0.47 mm In2 hop between vias 0.403 mm apart at (99.93,86.88)/(99.98,87.28) | with the re-route |
| N1 | NOTE | In1 VREG keepouts: the RP2350 reference keeps solid GND under L1/C11/C12. A third rule area is on **In4.Cu, which this board doesn't have** (generator leftover) | drop the In4 area; keep or drop the In1 slots with a decisions.md entry |
| N2 | NOTE | Parity items all benign; lib mismatches as explained above | none needed |
| N3 | NOTE | Silk warnings are gate-9 carry-overs | gate 9 |
| N4 | NOTE | Good: every LED 100 n has its VLED via within 0.3–0.5 mm; 129 GND stitching vias; all 479 vias 0.4/0.2; U2 has 3 GND vias, D3 and U3 one each; In2 pours coherent | — |

## To pass

1. `.kicad_dru`: add `(constraint connection_width (min 0.09mm))`, so a neck fails DRC. Add
   `track_width (min …)` for the `power` class, as LESSONS requires for current-carrying nets.
2. `gen_board.py`: add VBATT to the `power` class.
3. Lock XIN/XOUT on F.Cu as pre-routes (route.py). Remove the In4.Cu rule area.
4. Ultraroute must stop making overlap-only joints: `design/ultraroute-requests.md` #1. Until
   that is fixed, a re-route is judged by the `connection_width` DRC. If the request isn't
   met, a snap pass in route.py would be the stopgap, but LESSONS says router fixes go to
   ultraroute, so that needs the user's call.
5. Re-route (build stage `route`, booked through `reserve`), then re-run this gate and
   re-review.

## Re-route 2026-11-01 (ultraroute 0b9016f, build route stage)

Fixes 1–3 and 5 from "To pass" are applied (`design/decisions.md`, 2026-11-01): VBATT is in
`power`, with a 0.2 mm `track_width` floor for the class. There's a `connection_width (min
0.09mm)` rule, with its severity raised to error in `.kicad_pro` (KiCad's default is warning,
so the first run still passed). XIN/XOUT/XTAL_R are locked F.Cu pre-routes, and the In4 area
is gone. For fix 4, ultraroute fixed the track-to-track joints at our request.
`python3 build.py --only route` (booked through reserve) gave unconnected 0, 329 vias, and
"mended 1 joints where round ends only overlapped".

| check | evidence | ok |
|---|---|---|
| DRC | `kicad-cli pcb drc --schematic-parity --severity-all`: **4 errors (connection_width), 0 unconnected**, parity 28 (unchanged). Warnings: 34 silk_overlap, 23 silk_over_copper, 5 text_height, 3 lib_footprint_mismatch, 2 silk_edge_clearance, 1 via_dangling (route.py's locked 3V3 via (6.2,2.6), now unused), 1 track_dangling (VLED_C In2 0.07 mm stub at (92.33,102.68)) | **no** |
| connection width | U8.5 3V3 B.Cu **0.066 mm**: the pad's only track ends 0.03 mm outside it. U6.5 3V3 B.Cu **0.053 mm**: an end ~0.08 mm off the pad edge (the pad also has a west track). U6.2 3V3 B.Cu **0.043 mm**: a 0.02 mm track. gnd_back pour sliver at (112.46,91.73), 0.074 mm. VBATT and CHRG are clean | **no** |
| router joints | `necks.py`: 996 hits, but it now overcounts. Its narrowest hits are false: the 3V3 F.Cu one at (97.33,99.28) is inside `vreg_3v3_1`, and LEDC_D2 ends exactly on LED39 pad 2's edge (`HitTest(…, 0)` misses it). ultraroute says ~1,100 ends sit inside a neighbouring track, which is full-width copper. KiCad's `connection_width` is the authority now | see DRC |
| VBATT | BT1.1 → Q2.3: **98 mΩ** (was 289), 55.3 mm, all 0.4 mm, 6 vias. BT1.1 → U2.5: 97 mΩ, narrowest 0.25 mm for 0.5 mm. It still goes round the edge | yes |
| crystal | XIN 6.5 mm, XOUT 2.3 mm, XTAL_R 2.2 mm, all F.Cu, **0 vias** | yes |

**Still FAILED**, on the three track-to-pad necks: U8.5's is its only feed. They are router
joints onto pads, not the track-to-track kind 0b9016f fixed. Sent to ultraroute as request #2.
Not re-reviewed: the independent review runs once DRC is clean.

## Re-route 2026-11-01 (evening): ultraroute 5064384

Pin 0b9016f → **5064384** (ultraroute main, CI passed): their fix for track-to-pad joints,
request #2. Route log: "mended 14 joints where round ends only overlapped" and "mended 2 pad
joints where a track's end only reached the pad's edge". Unconnected 0, 372 vias.

That left two `connection_width` errors in KiCad's pour fill, not in router copper: gnd_back
0.056 mm and vled_r_plane 0.074 mm. Shapely erosion of the saved fill found no neck under
0.09 mm. Raising every zone's minimum width moves the errors around: 0.2 mm clears both, while
0.25 mm makes new ones on gnd_back. Routing ultraroute over 0.2 mm fills gave a different
route with 13 same-net via-pair necks. So route.py now routes over the usual 0.15 mm fills and
sets 0.2 mm (large planes only; the VREG pours stay at 0.15 for the LX finger) just for the
final refill. The route is the same as the 0.15 run (identical mend counts, seed 0, 1 thread).
Fill area change: vled_r 170.4 → 155.0 mm², gnd_back 450.9 → 439.6, the rest ≤ 3 %.

| check | evidence | ok |
|---|---|---|
| DRC | `kicad-cli pcb drc --schematic-parity --severity-all` (connection_width 0.09 mm as error): **0 errors, 0 unconnected**, parity 28 (as before). Warnings: 34 silk_overlap, 23 silk_over_copper, 5 text_height, 3 lib_footprint_mismatch, 2 silk_edge_clearance (all as before), and 1 via_dangling: route.py's locked 3V3 access via at (6.2,2.6), unused by this route | yes |
| connection width | 0 under 0.09 mm (KiCad) | yes |
| VBATT | BT1.1 → Q2.3: 112 mΩ, 56.2 mm, all 0.4 mm, 15 vias. BT1.1 → U2.5: 115 mΩ, 0.4 mm. It still goes round the edge | yes |
| VBUS | J1 → D3: 70 mΩ; J1 → U2: 71 mΩ; narrowest 0.2 mm (the floor), 0.5–2.1 mm at the pads | yes |
| VSYS / VLED | VSYS narrowest 0.23 mm; VLED_L/R narrowest 0.23, VLED_C 0.3 | yes |
| crystal | XIN 6.5 mm, XOUT 2.3 mm, XTAL_R 2.2 mm: F.Cu only, 0 vias (locked pre-routes) | yes |
| USB pair | USB_DP 21.0 / USB_DM 21.1 mm, 2 vias each | yes |
| In1 GND plane | no tracks on In1 | yes |
| renders | `design/renders/` regenerated 2026-11-01 (skill render.py) | — |

## Review: independent (stronger model, fresh context), 2026-11-01, route 5064384

The reviewer re-derived everything with its own kicad-cli/pcbnew/shapely scripts (scratch
plots in the session scratchpad). DRC 0 errors / 0 unconnected, 28 benign parity items, every
warning explained. No joint below 0.095 mm anywhere. VBATT 112 mΩ at 0.4 mm. Crystal F.Cu
with 0 vias over solid In1. USB 21.0/21.1 mm. In1 one piece (702 mm²). Every pour piece has
copper of its net.

Previous findings: B1, B2, M1, M2, M3, m2, m4 (except the locked via) and N1 are **resolved**.
m3 is accepted (NOTE-1). m5 is open (MINOR-4).

| # | sev | finding | resolution |
|---|---|---|---|
| MAJOR-1 | MAJOR | **Via holes in SMD pads: 124** (17 wholly inside a pad, 107 cutting a pad edge): 42 WS2816C VDD pads, 26 0402 pads, five U1 QFN pins (9/11/31/33/55), the USB-C vias on J1.A7/B7. Mask expansion 0 and the vias are tented, so each hole is open in the pad's aperture: solder wicks, starving LED VDD joints and tombstoning 0402s. 120 are the router's; 4 are route.py's deliberate ones. For comparison, the shipped rev 1 (43eadc1) had 18 (4 inside, 14 edge; author's count) | **open: user's call** (see status.json) |
| MINOR-1 | MINOR | Track-to-pad joints 0.110–0.123 mm, below the board's 0.127 mm minimum: U6 3V3 pads 2/3/5/8, LED8.4 LEDL_D7, LED9.4 LEDL_D8, LED29.2 LEDR_D9, LEDC_D1 at a via. Above JLC's 0.09, mA-level nets | raise connection_width to 0.127 and send to ultraroute as request #3 |
| MINOR-2 | MINOR | gnd_back sliver 0.095 mm at (112.46,91.73) between the IMU_INT1 edge track and the via at (112.25,92.41). No island if it etches away | small no-pour area or accept |
| MINOR-3 | MINOR | CHRG 3.1 mm, CHRG_DONE 3.1 mm, VBSENSE 1.3 mm, LIGHT 0.44 mm on In2 over the In1 VREG slots, under VREG_LX with no plane between. VBSENSE and LIGHT are ADC inputs | tracks-only rule area on In2 over the slots, or log acceptance (slow, RC-filtered) |
| MINOR-4 | MINOR | USB_C_DP: 6 vias on 10.6 mm including a 0.52 mm In2 hop, a collinear back-track at (100.42,87.14); USB_C_DN 15° joint at (100.12,87.46). Fine at 12 Mb/s | cosmetic |
| MINOR-5 | MINOR | Overlapping VLED_L In2 tracks from the via at (94.98,82.33), 1.8° apart; the unused locked 3V3 via (106.2,102.6) with its 1.4 mm In2 stub | strip in the route stage |
| NOTE-1..3 | NOTE | USB full white: 32 °C rise on the 0.4 mm In2 VBUS/VSYS at 0.62 A; D3's ~0.5 W is the real limit (decisions.md accepts on the 140 mA cap). VREG_LX 1.65 mm at 0.127 mm before the pour is fine. Renders looked at | — |

**Verdict: FAIL** on MAJOR-1 alone. If MAJOR-1 is settled by a decision (filled and capped
vias), this gate passes without a re-route. If it's settled by a hole-clearance rule, the
board needs a re-route and this gate re-runs.

## Re-route 2026-11-02: ultraroute 99bb7ca, seed 1, via-hole rule

The board has new inputs since the review above:
- the `.kicad_dru` rule "No via hole in SMD pad" (`physical_hole_clearance` 0.1 mm, via to SMD
  pad), with route.py's own vias moved off pads (1f12b22);
- KiCad UUIDs seeded in route.py, so the router's input is byte-identical from run to run
  (eee01cd);
- ultraroute pin 5064384 → 99bb7ca, which fixes request #3 (exact hole clearance; touching
  same-net vias) and the joint-floor bug behind request #4;
- recipe `--seed 0` → `--seed 1` and `--timeout 240` → `480`. On this input seed 0 leaves 3
  unconnected; seeds 1–3 route everything. Ultraroute swept the seeds on
  `ultraroute-lab/repro/earring-seeded`.

The route stage took 219 s and left 0 unconnected.

| check | evidence | ok |
|---|---|---|
| DRC | `kicad-cli pcb drc --schematic-parity --severity-all`: **1 error, 0 unconnected**, parity 28 (as before). The error: connection_width 0.077 mm in the gnd_front fill at (112.46,91.73), MINOR-2's sliver (now on F.Cu). Warnings: 34 silk_overlap, 23 silk_over_copper, 5 text_height, 3 lib_footprint_mismatch, 2 silk_edge_clearance (all as before); via_dangling, the unused locked 3V3 via at (106.2,102.6); track_dangling, a 0.21 mm VLED_L F.Cu stub at (93.38,88.58) | **no** |
| via in pad | 0 hole_clearance errors under the 0.1 mm via-to-SMD-pad rule | yes |
| VBATT | BT1.1 → Q2.3: **63 mΩ**, 29.5 mm, all 0.4 mm, 4 vias (was 112 mΩ, 56 mm round the edge) | yes |
| VBUS | J1 → D3: 50 mΩ, 0.4 mm. J1 → U2.4: 63 mΩ, narrowest 0.25 mm. Net minimum 0.20 mm (the floor) | yes |
| VSYS / VLED | VSYS narrowest 0.23 mm; VLED_L 0.30, VLED_R 0.23, VLED_C 0.23 | yes |
| crystal | XIN 6.5, XOUT 2.3, XTAL_R 2.2 mm: F.Cu only, 0 vias | yes |
| USB pair | USB_DP / USB_DM 20.7 / 20.7 mm, 2 vias each. USB_C_DP / USB_C_DN 11.9 / 11.0 mm, 4 vias each (was 6 on DP: MINOR-4) | yes |
| In1 GND plane | no tracks on In1 | yes |

**Gate 7 still FAILS**, on the gnd_front fill sliver alone. That needs the user's call: a small
no-pour area there, or log the sliver as a known fill artefact. No independent re-review yet: it
runs once DRC is clean.
