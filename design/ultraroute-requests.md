# ultraroute change requests

Router problems found on this board, for the ultraroute project to fix. Per the skill's
LESSONS, the fix belongs in the router, not in a workaround script here.

## 1. Overlap-only track joints (2026-10-31, gate 7)

**Seen in:** ultraroute 8c691ec (lab), `~/Software/ultraroute-lab/experiments/vled-width-1/s0`.
The pinned `vendor/ultraroute` 0330831 is not yet checked.

**What:** the output has 81 joints where two tracks of a net don't share an endpoint. Their
ends sit 0.05–0.28 mm apart (often exactly one 0.1 mm grid step diagonally: 0.141 mm), and
the copper connects only where the round ends overlap. The input board has none:

    tools/route_audit/necks.py …/s0/input.kicad_pcb   -> 0 overlap-only joints
    tools/route_audit/necks.py …/s0/out.kicad_pcb     -> 81 overlap-only joints

KiCad counts these as connected, and the default DRC passes them. With a `connection_width
(min 0.09mm)` rule, KiCad reports necks down to 0.051 mm. Two are the only battery path
(VBATT In2 at (98.68,88.08) and (107.3,108.35)) and one is CHRG's only path (F.Cu at
(101.33,110.83)).

**Ask:** every track joint the router writes should be a shared endpoint (or a T onto a
segment's centreline), never an end-cap overlap. A self-check before writing would help:
no joint narrower than the net's width rule.

**Status (2026-11-01):** still present: the installed board still has 81. Not fixed on
ultraroute origin/main as of cc6be09 (b5f9f2d's 0.5 µm reach-in rule still accepts these
joints). Sent to the ultraroute session (ultraroute-e8), along with a second ask: fail the run when
any joint is narrower than the net's width rule, so this can't be reported as success again.

**Fixed** in ultraroute 0b9016f (2026-11-01) for track-to-track joints. Re-routed here: VBATT
and CHRG are clean.

## 2. Track-to-pad joints narrower than the fab minimum (2026-11-01, gate 7 re-route)

**Seen in:** pinned 0b9016f, build route stage. KiCad `connection_width (min 0.09mm)`:
- U8.5 3V3 B.Cu: 0.066 mm. The pad's only track ends just outside it at (103.675,93.162).
- U6.5 3V3 B.Cu: 0.053 mm. A track end at (109.65,88.55), ~0.08 mm off the pad's edge.
- U6.2 3V3 B.Cu: 0.043 mm, from a 0.02 mm track at (107.84,89.13–89.15).

**Ask:** a track that ends on a pad ends inside the pad's copper, so the joint is at least the
track's width (or the net's minimum). Report any narrower pad joint, as 0b9016f does for track
joints. Sent to the ultraroute session 2026-11-01.

**Fixed** in ultraroute 5064384 (2026-11-01). Re-routed here: no pad joint under 0.09 mm.
