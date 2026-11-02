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
