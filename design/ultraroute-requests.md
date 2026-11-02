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
