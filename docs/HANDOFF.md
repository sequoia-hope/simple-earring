# HANDOFF — ALL FIVE TASKS COMPLETE (2026-08-05)

> **Status: done.** 1 back-port `377d81b` · 3 RP2350A+flash `c4c675f` ·
> 2 LED swap `4428941` · 4 schematic `a5cc59e` · 5 4-layer `0513be3`.
> The 4-layer attempt did not converge and was handed to Sequoia as a
> partial board at his request — see **`docs/PUNCHLIST-4layer.md`**, which
> supersedes Task 5 below. `out/earring.kicad_pcb` is now hand-routed
> territory: do not rebuild over it.
>
> The task descriptions below are kept for the reasoning and the
> landmines, not as a work queue.

---

# (original) next revision tasks, written 2026-08-05

Context: Sequoia hand-edited the routed board in KiCad and we started tracking
PCB versions in git. This doc is the work queue for the next session. Read
`docs/PLAN.md` first (plan of record, constraints, dashboard workflow) and the
project memory files (pcbnew gotchas, freerouting integration) before touching
anything.

## What already happened (committed, do not redo)

- Commit `664bcd5`: `.gitignore` now tracks `out/earring.kicad_pcb` and
  `out/earring.kicad_pro` (rest of `out/` still ignored; `logs/` now ignored
  too). The committed board contains Sequoia's HAND EDITS on top of the
  generated build 11 (121 parts, 0 DRC):
  1. **USB diff pair rename** — D+/D- nets renamed so KiCad treats them as a
     differential pair (same name except trailing p/n). The board now contains
     nets `USB_C_DP`/`USB_C_DN` *and* the old generator names
     `USB_DM`/`USB_DP` — probably connector-side vs post-ESD (USBLC6-2P6)
     segments; verify which is which in the board before renaming in source.
  2. **USB power rerouted with wider traces** — measure the widths Sequoia
     used on the board (VBUS path) and adopt them.
  3. **Under-CPU power routing cleaned up** — the auto-routed power under U1
     had gotten sloppy; Sequoia redid it by hand.

⚠ The generator will OVERWRITE these edits on the next `python3 build.py`.
Task 1 must land before any rebuild, or the edits must be re-applied from git.
`git show 664bcd5:out/earring.kicad_pcb` always recovers the hand-edited board.

## Task 1 — back-port the hand edits into the generator

Goal: a fresh `python3 build.py` reproduces the intent of the hand edits.

- Baseline for diffing: check out / rebuild from `9d3bbb6` into a scratch dir
  (or use `out/earring-backups/earring-2026-08-05_*.zip`, but the earlier
  zips may already contain partial edits — a scripted rebuild is the clean
  baseline). Diff nets, track widths, and segment geometry against the
  committed board.
- USB diff pair: rename the nets in `scripts/circuit.py` to the trailing-p/n
  convention (match what Sequoia chose, e.g. `USB_C_DP`/`USB_C_DN` and a
  post-ESD pair name), and make `scripts/route.py` route them as a coupled
  pair (freerouting has no real diff-pair support — the practical approach is
  scripted parallel routing for that short run, or lock the hand-routed pair
  copper and exclude it from freerouting; see `scripts/check_locked_copper.py`
  and the freerouting-integration memory).
- USB power width: add a net-class / width rule for VBUS (and its path to the
  charger) in the generator rather than hardcoding segments, if possible.
- Under-CPU power: reproduce via placement/routing constraints, or preserve
  Sequoia's copper verbatim as locked pre-routes that freerouting must keep.
  Preserving verbatim is likely more faithful and cheaper than re-deriving.
- Acceptance: rebuild → 0 DRC, and a visual diff on the :8618 dashboard shows
  USB pair symmetric, VBUS fat, under-U1 tidy. Then commit the regenerated
  `out/earring.kicad_pcb` so the tracked board = generated board again.

## Task 2 — replace the LED (TBA-C1010MB-J2I16 is out of stock)

Current part: `bom/parts.yaml` → mpn TBA-C1010MB-J2I16, LCSC C22461778,
footprint `LED_TBA-C1010MB` (1010, pins 1=DI 2=VCC 3=GND 4=DO, per
`scripts/circuit.py`).

- Find an in-stock 1010-package addressable RGB LED at LCSC (WS2812-protocol
  1010 candidates exist from XINGLIGHT/TCWIN/others — verify live stock and
  price, don't trust memory).
- Check against our constraints before adopting:
  - **Pinout + pad geometry** vs our generated footprint (`library/` /
    `scripts/gen_footprints.py`); regenerate footprint if pads differ.
  - **Supply range**: LEDs run on VLED = VBATT (LiR2032, ~3.0–4.2 V), see
    `design.yaml` note — the TBA part is officially 4.2–5.5 V but works at
    LiR voltage; the replacement must too.
  - **Data VIH**: DI is driven at 3.3 V from the RP2350 while VDD is VBATT
    (up to 4.2 V). WS2812-class parts want VIH ≥ 0.7·VDD ⇒ 2.94 V at 4.2 V —
    tight but the same situation as today; confirm the replacement's VIH spec
    is no worse.
  - Timing/protocol compatible with existing firmware assumptions (standard
    WS2812 800 kHz).
- Update `bom/parts.yaml`, `scripts/circuit.py` (part name + pin map if
  changed), `design.yaml` comments, and rebuild.

## Task 3 — RP2354A is out of stock → RP2350A + external QSPI flash

Current: `bom/parts.yaml` U1 = RP2354A, LCSC C41378174, QFN-60.
`scripts/circuit.py` already documents: RP2354A == RP2350A pinout; QSPI pins
currently NC except QSPI_SS. So the footprint and all existing routing stay.

- Swap U1 to RP2350A (find/verify LCSC number + stock).
- Add a QSPI NOR flash (W25Q-family, e.g. W25Q128JV or a smaller 16/32 Mbit
  part — pick by LCSC stock and by what fits; USON-8 3×2 mm or 4×3 mm is the
  space-realistic choice on this board, SOIC-8 is likely too big). Verify the
  chosen part is RP2350-boot-compatible (standard 03h/6Bh/EBh reads — W25Q is
  the reference part).
- Circuit: wire QSPI_SD0..SD3, QSPI_SCLK, QSPI_SS from U1 to the flash, add
  100 nF decoupling at the flash VCC, flash VCC on 3V3. No pull-ups required
  for the standard boot flow (QSPI_SS has the internal boot-strap behavior —
  keep whatever strap the RP2354A design already had on QSPI_SS).
- Placement: board is a tiny teardrop and build 11 was already tight at 121
  parts. Flash wants to be adjacent to U1 with short matched-ish QSPI runs
  (<10 mm ideally). Check the back side opposite U1 first (vias through —
  mind the In2/In4 power planes) or steal room in the MCU cluster; consult
  the ring/keepout geometry notes in memory + `docs/PLAN.md` constraints.
- `bom/parts.yaml` gets the flash entry (mpn, lcsc, footprint,
  `verified:` per the file's convention); footprint into `library/` or
  `gen_footprints.py`.
- Rebuild through DRC + dashboard review.

## Task 4 — generate a schematic (Sequoia needs one to make sense of the design)

There is no schematic today — the netlist is code (`scripts/circuit.py`).
Deliverable: a readable schematic Sequoia can open/print.

Recommended approach: a new `scripts/gen_schematic.py` stage that emits
`out/earring.kicad_sch` from the same `circuit.py` data:

- KiCad 9 `.kicad_sch` is a writable s-expr format; generate symbols +
  **global net labels** instead of drawn wires between sections — this keeps
  the generator simple and the sheet readable.
- Organize into functional groups on the sheet: power-in/USB, charger, LDO +
  load switch, MCU + VREG parts, QSPI flash (new), IMU, LED chain (collapse
  the LED ring to first/last + "×N" repetition note or one sheet per ring is
  overkill — a single LED symbol with the chain annotated is fine).
- Reuse/derive symbols: kicad's bundled symbol libs cover generic R/C/L,
  USB-C, SOT LDOs; the MCU/IMU/LED may need simple generated box symbols
  (pin name + number is all that matters for readability).
- Track `out/earring.kicad_sch` in git (add a `!out/earring.kicad_sch`
  negation to `.gitignore`).
- No ERC perfection required — this is documentation, correctness of
  net-to-pin mapping is what matters. Add it to `build.py` STAGES so it
  regenerates with the board.

## Task 5 — attempt a 4-layer version (timeline-driven)

Sequoia has a tight timeline: 6-layer (JLC06161H-3313) isn't much more
expensive but has a longer JLCPCB lead time; 4-layer ships faster. Try to
get the design to converge on 4 layers.

- Current 6-layer plane roles are documented in `design.yaml` /
  `docs/PLAN.md` (In1 = GND, In2 = power VLED-annulus + 3V3 disc, In4 =
  solid VLED). A 4-layer stackup (e.g. JLC04161H-7628 or 3313) leaves only
  In1 + In2: the obvious split is In1 = GND, In2 = shared power (VLED
  annulus + 3V3 disc merged onto one plane), with VLED interior drops
  rerouted or moved to outer-layer copper. Expect the interior-LED VLED
  feed (previously "anywhere via drop into solid In4") to be the hard part.
- The board converged on 4 layers in an earlier revision (pre-IMU, 121
  parts) — the IMU/interior-LED revision is what went to 6. It may fit
  again; freerouting effort will tell.
- Implementation: make layer count / stackup a `design.yaml` switch if it
  isn't already, so 4- and 6-layer builds can be generated side by side and
  compared on the dashboard. Keep the 6-layer config as fallback — if
  4-layer won't converge DRC-clean in a few attempts, ship 6-layer and eat
  the lead time (Sequoia's call; present both results).
- **If routing fails to converge (likely): hand the BEST partial result to
  Sequoia for manual completion in KiCad.** Concretely:
  - Across all routing attempts, keep the board with the fewest unconnected
    nets / DRC errors (not the last attempt) — snapshot each attempt's
    result + stats so "best" is selectable after the fact.
  - Deliver it as a saved, committed `out/earring.kicad_pcb` (zone fills
    done, no stale `.lck`), on a branch or clearly-messaged commit so it's
    distinguishable from a converged build.
  - Include a short punch list: which nets are unconnected / which DRC
    errors remain, roughly where (refs + area), and any known blockers
    (e.g. congestion under U1, VLED feed) — on the dashboard and/or in the
    commit message.
  - After Sequoia finishes it by hand, their copper is the source of truth
    for that build: same rule as the current hand edits — don't rebuild
    over it; back-port or lock before any regeneration.
- **Interaction with Task 1**: a 4-layer reroute discards all hand-edit
  copper. So back-port the hand edits as *generator rules* (net names,
  VBUS width class, diff-pair handling) — those carry over to any stackup —
  and only rely on verbatim locked-copper preservation for the 6-layer
  fallback. Do Task 1's rule-level work first, then the 4-layer attempt
  includes those rules from the start.
- **Interaction with Tasks 2/3**: do the part swaps before the 4-layer
  attempt so you only fight convergence once, with the final netlist
  (incl. QSPI flash).

## Suggested order & verification

1 (back-port as generator rules, protects the hand edits) → 3 (RP2350A+flash,
changes netlist & placement) → 2 (LED swap, may also touch
placement/footprint) → 5 (4-layer attempt with the final netlist; 6-layer
fallback stays available) → rebuild through `python3 build.py` (0 DRC) →
4 (schematic) → commit tracked outputs.

Every board-touching task ends with: `python3 build.py` clean, DRC 0 errors,
renders reviewed on the :8618 dashboard, then commit `out/earring.kicad_pcb`
(+ `.kicad_pro` if changed) alongside the source change so the tracked board
never drifts from the sources.

Pitfalls already learned the hard way (details in project memory): pcbnew
`Delete` vs `Remove` segfault, courtyard caches going stale, DSN/SES quirks,
freerouting v2 headless hangs — use the existing pipeline scripts, don't
hand-roll new pcbnew invocations.
