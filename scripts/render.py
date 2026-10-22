#!/usr/bin/env python3
"""Render top/bottom PNGs (3D raytrace) and layout-view SVGs (2D, PCB
editor look: viewed side's copper frontmost, other layers behind) of the
board for visual review, and generate the out/ dashboard that serves them.

  render.py                 full render + dashboard
  render.py --placement     quick post-place preview only (no routing yet)
  render.py --index-only    rewrite out/index.html, touch nothing else

The dashboard is a reverse-chronological feed (see FEED below) over the top
of the live build outputs. It is generated HERE, not edited in out/ — hand
edits to the served page get silently wiped by the next build, which has
already cost one banner (3528329)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PCB = ROOT / "out" / "earring.kicad_pcb"

def _copper_layers():
    """Copper layer names F->B for the configured stackup (4 or 6)."""
    from circuit import load_design
    n = load_design()["board"]["layers"]
    return ["F.Cu"] + [f"In{i}.Cu" for i in range(1, n - 1)] + ["B.Cu"]


_COPPER = _copper_layers()

# layers listed back-to-front; kicad-cli draws them in list order
LAYOUT_VIEWS = {
    "top": (",".join(_COPPER[::-1] + ["F.Silkscreen", "Edge.Cuts"]), False),
    "bottom": (",".join(_COPPER + ["B.Silkscreen", "Edge.Cuts"]), True),
}

# individual copper layers (all drawn from the top, unmirrored, so the
# transparent PNGs stack in register in the grid and the layer viewer)
LAYER_STACK = [(ly, ly.split(".")[0].lower()) for ly in _COPPER]

# ---------------------------------------------------------------- feed ----
# The dashboard is a reverse-chronological log, not a snapshot: the board
# has been through three revisions and two bench debug campaigns, and the
# useful question is almost always "what changed since I last looked", not
# "what does the current PNG show". Entries are collapsed by default except
# the newest, so the live outputs below stay one scroll away however long
# the log gets.
#
# This lives in the GENERATOR, not in out/index.html. Hand edits to the
# served page are wiped by the next render — that already happened once
# with the R8 rework banner (see 3528329). Add a dict at the top of FEED.
#
# date  : ISO, shown as "Aug 31"
# sha   : commit this entry describes, or None for bench findings that
#         produced no commit (the debug campaigns are the useful ones)
# tags  : keys of TAGS below
# lede  : one sentence, always visible in the collapsed summary
# body  : HTML, revealed on expand
# media : (src, caption, live) — live=True joins the 15s auto-refresh, for
#         images the build regenerates; historical shots stay static so a
#         collapsed entry costs nothing to have on the page
TAGS = {
    "hardware": "#fc6",
    "firmware": "#8f8",
    "layout": "#9cf",
    "case": "#c9f",
    "bench": "#f88",
    "tooling": "#7dd",
    "bom": "#fb8",
    "milestone": "#ffd24d",
}

FEED = [
    dict(
        date="2026-10-22", sha=None, tags=["hardware", "layout", "milestone"],
        title="LiPo instead of the coin cell: LPR302823 round pouch, wire pads, "
              "and a soft-latch power button where the slide switch was",
        lede="140&nbsp;mAh (~120 at 4.2&nbsp;V) against 85, in a 4.7&nbsp;mm "
             "stack against 3.8. Placed and DRC-clean, <b>not routed yet</b>: "
             "waiting on brief sign-off.",
        body="""
<p><b>The cell.</b> LiPol <b>LPR302823</b>: Ø28&nbsp;mm round pouch with one
flat, PCM inside the outline, 3.0–3.2&nbsp;mm, 140&nbsp;mAh, 70&nbsp;mA max
charge. It is a 4.35&nbsp;V "HV" cell, but it stays on the 4.20&nbsp;V
LGS4056H on purpose: its PCM overcharge trip can be as low as 4.305&nbsp;V.
R8 goes 22k&nbsp;→&nbsp;18k (50&nbsp;mA, 0.36C). The cell is taped to the back
on 1.5&nbsp;mm VHB over parts no taller than 1.1&nbsp;mm, flat facing the tip,
and its wires go to two pre-tinned pads, one each side of J1, ≥0.6&nbsp;mm
from any other copper.</p>

<p><b>The slide switch had to go.</b> Its inner corner sits 9.4&nbsp;mm from
centre, inside any Ø28 circle. A sweep against real copper found no cell angle
that cleared both it and J1. It is replaced by an <b>Omron B3U-3000P
side-push</b> button higher up the left tip edge, plus a <b>soft latch</b>
(Q4 CJ2101, Q5 BSS138W, D4 BAV70W, R24/R25, C27). Press and the CPU wakes;
it drives <b>GPIO20 PWR_HOLD</b> to stay on and reads the button on
<b>GPIO21</b>; a long press turns it off. Off-state drain is ~µA.
<b>Firmware must now hold PWR_HOLD</b>, or the board turns off when you let go
of the button.</p>

<p><b>What it frees.</b> BT1's Ø8 GND centre pad and the six-bump hack are
gone, along with route.py's "no vias inside r&nbsp;4.6" rule. That disc is
what stranded LIGHT and VBUS_SENSE in rev 2's route.</p>

<p><b>Reviews.</b> Four independent passes (parts, brief, latch circuit,
placement) caught real problems that are now fixed:</p>
<ul>
<li>a cell rotation that only cleared J1 by courtyard, not by copper;</li>
<li>pads 0.27&nbsp;mm from VLED vias;</li>
<li>a Schottky in the latch that would have switched the board on by itself
in a hot car (now a silicon BAV70W);</li>
<li>a shapely-vs-KiCad rotation-sign mismatch.</li>
</ul>
<p>Everything is in <code>design/</code>: intent, brief, decisions, gates
0/1/2/4/6.</p>
""",
        media=[("lipo_fit.svg",
                "Back view: the cell's worst-case envelope against every "
                "back-side part, the pads and the button; and the stack "
                "height against the coin cell.", True),
               ("render_place_bottom.png", "back, placed (unrouted)", True)],
    ),
    dict(
        date="2026-08-31", sha=None, tags=["bom", "hardware"],
        title="C22363833 would retire the six-bump GND hack — but its land runs "
              "off the board, and the only place it fits is on top of J1",
        lede="A socket carries its own negative contact, so it needs no Ø8 "
             "centre pad. The land is 1.19&nbsp;mm too wide, and it is "
             "1.9&nbsp;mm taller.",
        body="""
<p>The MY-2032-12-R is a <i>retainer</i>: it clamps the coin against a bare Ø8
pad on the back, and that pad is the negative terminal. That is the awkward
requirement on this board — 176 B.Cu track endpoints sit inside r9.5, and 35µm
of copper under 20µm of mask stands ~25µm proud of a bare pad face, so the rigid
coin rode on soldermask and never touched copper. Today's answer is a ring of
six mask-defined solder bumps (<code>gen_footprints.py</code>), which works but
is a hack standing in for a land we could not give it.</p>

<p>A <b>socket</b> removes the requirement outright: the negative contact is a
tab inside its own base, so the board only needs two ordinary end pads and the
copper under the coin becomes irrelevant. <b>C22363833</b> (Lianxin CR2032-BS-6,
gold, SMT, 11k in stock at $0.19/50) is exactly that part class, and its
mounting drawing confirms it — <b>two pads, no centre land</b>.</p>

<h4>Read the outline, not the bounding box</h4>
<p>The first pass of this test drew the part as its <b>31.9&nbsp;×&nbsp;16.0
bounding rectangle</b>, and that was wrong in a way worth recording. The plastic
body is only <b>28.8&nbsp;long with C1.5 chamfered corners</b>; the ends that
reach 31.9 are narrow <b>7.1&nbsp;mm metal solder tabs</b>. Treating the box as
the body overstated the plastic overhang <b>~5×</b> — 2.50&nbsp;mm claimed
against <b>0.55&nbsp;mm</b> real, at one chamfer vertex. The other chamfer
vertex is <i>inside</i> the edge by 0.07&nbsp;mm. Panel 1 and 2 above now draw
the true outline; grey is metal, red is plastic.</p>

<h4>What actually blocks it</h4>
<ul>
<li><b>The land is wider than the board — this is the real one.</b> Pads sit at
<b>±15.30&nbsp;mm</b>; the round body is <b>R&nbsp;15.25</b>. Pad corners reach
16.44&nbsp;mm, so a centred part hangs <b>1.19&nbsp;mm</b> past the edge. That
is metal-tab geometry against board outline: <i>no amount of re-placement moves
it</i>.</li>
<li><b>…but rotating it does find a legal land.</b> Sweeping position ×
rotation turns up <b>2227 placements where both pads sit fully on copper</b> —
all of them rotated ~70–110° so the land runs down the long tip axis, which is
35.75&nbsp;mm against the 30.5&nbsp;mm width. The best is
(+1.75,&nbsp;−2.50)&nbsp;@&nbsp;72°. <b>Every single one puts the body on top of
J1</b>, the USB-C receptacle — and J1 is not a part placement can move: it is
pinned by the tip geometry and its 1.3&nbsp;mm mating-face overhang. Those
placements also push the plastic overhang back up to ~1.9&nbsp;mm.</li>
<li><b>It sits flat — and this one is soft.</b> The incumbent touches down on
two 3.0×4.5 feet at ±12.4 and arches over everything between them, which is the
only reason a back side this crowded works. The BS-6's base covers <b>12 of the
23 back-side parts</b> (TP1/TP2/R11/C21 completely, plus SW2, Q2, D2, C23, C24,
R12, R17, TP3). Correcting the outline did <i>not</i> reduce that count — it is
the 16&nbsp;mm width that catches them, not the ends. But unlike the land, these
are ordinary passives and test points: <b>re-placement could clear them</b>, so
this should not be counted as a blocker.</li>
</ul>

<h4>And it is taller</h4>
<p><b>5.5&nbsp;mm vs 3.60&nbsp;mm — +1.9&nbsp;mm, 53%.</b> Worse, that 5.5 is
drawn around a 3.2&nbsp;mm CR2032 and the fitted cell is a 3.6&nbsp;mm
RJD2032C1. A spring clip splays 0.4&nbsp;mm; a moulded pocket does not. It would
also push the case's <code>--bat</code> (5.30&nbsp;mm) up rather than let it
shrink.</p>

<p><b>What this establishes as the real requirement:</b> a self-contained
two-terminal holder with a land pitch inside <b>±13&nbsp;mm</b> and a height at
or under ~4&nbsp;mm. <code>parts.yaml</code> already tracks BAT-HLD-001 (±11.43)
and MPD BC-2003 as near-misses on the clip side; the socket side has not been
surveyed against those two numbers yet. Diagram from
<code>scripts/gen_bs6_svg.py</code>, which reads the board live, so the
collision list cannot drift.</p>
""",
        media=[("bs6_fit.svg",
                "1: the incumbent lands on two feet and bridges the rest. "
                "2: the BS-6 centred — land 1.19mm off the edge. 3: rotated "
                "into the only land-legal window, where the body lands on J1. "
                "below: the 1.9mm height penalty.",
                False)],
    ),
    dict(
        date="2026-08-31", sha="bdc87fc", tags=["layout"],
        title="Rev 2 routed to 5 unconnected / 0 errors — and the retry loop "
              "is not buying what it claims",
        lede="1371 tracks, 258 vias, zero DRC errors. Five nets stay open, and "
             "five of the six seeds returned the same answer.",
        body="""
<p>First routed board carrying the rev-2 power path. <b>0 DRC errors</b>, 117
warnings (60 silk-over-copper, 40 silk overlap, 6 dangling vias — the usual
crop), and five unconnected nets. The renders and layer stack above are this
board.</p>

<h4>What is still open</h4>
<ul>
<li><code>VBUS_SENSE</code>, U1.41 &rarr; R19.2 — <b>8.2&nbsp;mm cross-board</b></li>
<li><code>LIGHT</code>, U1.40 &rarr; Q1.2 — <b>7.3&nbsp;mm cross-board</b></li>
<li><code>VBUS</code> &times;2 — the tip trunk (the 3 segs route.py reported
blocked by routed copper) and the short branch to the new R19</li>
<li><code>3V3</code>, a 1.6&nbsp;mm stub at the MCU</li>
</ul>
<p>The two long ones share a cause. Both leave the MCU&rsquo;s jammed west pin
window — pins 40 and 41, at radius <b>3.45</b> and <b>3.51&nbsp;mm</b> — and have
to reach the east side. The obvious shortcut is a B.Cu hop straight across, but
BT1 sits on the back with a Ø8 GND pad dead centre, so the back inside r4.0 is
solid copper and a via wants r&nbsp;&gt;&nbsp;4.4. Both nets therefore
<i>originate inside the blocked disc</i>: they have to escape radially on F.Cu
past the coin before the back layer is available at all. That is why the trick
that works for this board&rsquo;s other stranded nets — one committed
B-transition via at the pin — does not apply here.</p>

<h4>Six seeds, one sample</h4>
<pre class="art">attempt 1   route 19 -> finish  5   <- best, kept
attempt 2   route 30 -> finish 14
attempt 3   route 30 -> finish 13
attempt 4   route 30 -> finish 14
attempt 5   route 30 -> finish 14
attempt 6   route 30 -> finish 14</pre>
<p>Attempts 2-6 routed to <b>exactly 30</b> every time. That is not seed
variance, and the retry unit in build.py is built on the assumption that it is
(&ldquo;freerouting is seed-dependent, so a failed finish re-rolls the routing&rdquo;).
Only attempt 1 differed, and the one thing that made it different is that it
started from a board that had never been through a completed route — the earlier
run hung in freerouting, so it left pre-routes and zones but no post-route pours,
keepouts or ring stubs. Attempts 2-6 each started from the previous attempt&rsquo;s
finished board. <code>wipe()</code> does delete every track and zone, so the
mechanism is not obvious and <b>I have not proven it</b> — but the pattern is
strong enough to say the loop cost ~2.5&nbsp;h to produce one real sample, and
that resetting to the freshly-placed board between attempts is worth testing
before trusting the next six-attempt run.</p>

<p class="note">Not ordered, not orderable: five open nets. Fab export was
deliberately skipped for that reason.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-31", sha="c0cd016", tags=["layout", "tooling"],
        title="Freerouting hung before pass 1 — a locked polyline, not congestion",
        lede="The first full route since rev 3 never started. Bisected to "
             "LED_D3&rsquo;s locked hop; cut to one segment, and the board "
             "routes again.",
        body="""
<p>Symptom: silent, 100&nbsp;% CPU, <b>nothing in freerouting&rsquo;s own log
after the settings dump</b>, both 900&nbsp;s tries burned, no SES, twice. The
static gate was clean — <code>kicad-cli</code> DRC with the
<code>.kicad_pro</code> beside the board reports 0 errors on the pre-freerouting
statics — so this was not the known locked-wire-clearance burn.</p>

<p>A hang is deterministic, so the retry loop was just burning 30&nbsp;min an
attempt. Bisected instead by deleting <code>(wire …)</code> blocks from the DSN
and probing at <code>-mp 2</code> (~90&nbsp;s each), run concurrently with a
per-probe <code>-Djava.io.tmpdir</code> so each got its own log. Verdict is
simply whether <code>Pass #</code> ever appears:</p>

<pre class="art">full hop                 HANG     only CHRG_DONE dropped   HANG
hop dropped entirely     routes   hop's 3 middle segments  HANG
segment 2 alone          routes   segments 2 + 3           HANG
segment 3 alone          routes   segments 1 + 2 + 3       HANG</pre>

<p>So the trigger is a fixed <b>polyline</b> — any two of those segments meeting
at a vertex is enough. <b>My standing note on this was wrong.</b> It blamed
&ldquo;fixed wires that start on a component pad&rdquo;, but CHRG_DONE is a
seven-segment fixed chain landing in U2&nbsp;pad&nbsp;6 and it routes; the VLED
C32&rarr;C30 link touches a pad at <i>both</i> ends and it routes; and trimming
LED_D3&rsquo;s two pad-landing segments off while keeping the three middle ones
still hangs.</p>

<p>The hop keeps its one load-bearing segment, the vertical past SW2&rsquo;s NPTH
peg. A lone fixed fragment still does the job because freerouting has to reach
both of its ends — the wire is forced through the corridor and it does the two
pin escapes itself. All four probe SES files come back with the same LED_D3 wire
count with or without it. Same shape as the trick that already works for stranded
nets here: one committed B-transition via, never a locked path.
<b>Single hints work, locked paths poison.</b></p>

<p>Two things fixed alongside. Both tries timing out left <code>r</code> as
<code>None</code>, so <code>route.py</code> printed <i>no diagnostic at all</i>
for the one failure mode that most needs one; it now reads freerouting&rsquo;s log
and reports the pass count for the current run, calling out &ldquo;hung before
pass 1&rdquo; explicitly. And worth knowing while reading that log:
<code>/tmp/freerouting</code> is shared by every project on this machine and
appends across runs — the 241k <code>PolylineTrace.normalize</code> lines that
looked like this board live-locking turned out to be a different project&rsquo;s,
from Aug&nbsp;29.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-31", sha="2e9399c", tags=["hardware", "layout"],
        title="Rev 2 power path: split VBATT from VSYS so USB runs the board",
        lede="The root fix for &ldquo;no lights at all&rdquo; — the charger&rsquo;s "
             "41&nbsp;mA no longer feeds the running board, so the cell actually "
             "charges and the ring lights at any state of charge.",
        body="""
<p>Rev 1 hung the LDO input and the LED load switch on <code>VBATT</code> — the
same node as the charger&rsquo;s BAT pin — so the LGS4056H&rsquo;s ~41&nbsp;mA
program current was <b>shared with the running system</b>. 17&nbsp;mA of MCU plus
17.5&nbsp;mA of LED rail left the cell about 6&nbsp;mA, and a flat cell could
never climb to the SK6805-EC10&rsquo;s 3.7&nbsp;V minimum VDD before someone
unplugged it. That is a power-path problem, not a firmware one.</p>

<pre class="art">VBUS  --|&gt;|--  VSYS      D3, B5819WS Schottky, ~0.3V at our ~60mA
VBATT --[Q2]-- VSYS      CJ2101 P-FET, on only when no cable is in
VSYS  -&gt; U3 (LDO IN), U4 (LED load switch IN), C18, C29
VBATT -&gt; U2 pin 5 (charger BAT), BT1, C17, SW2   [cell node ONLY]</pre>

<p><b>Q2&rsquo;s orientation is the whole trick:</b> source&nbsp;=&nbsp;VSYS,
drain&nbsp;=&nbsp;VBATT. A P-FET&rsquo;s body diode conducts drain&rarr;source, so
this way it points cell&rarr;VSYS. It blocks the 4.7&nbsp;V USB rail from
back-feeding the cell around the charger — which is exactly what the intuitive
wiring (source on the battery) would do through the body diode — while still
letting the cell carry the load through ~0.4&nbsp;V of diode if VSYS sags below
VBATT, covering the ~200&nbsp;ms of VBUS decay on unplug. The gate is R22
10k&nbsp;from VBUS against R21 1M&nbsp;to GND: near VBUS with a cable in
(Vgs&nbsp;+0.25&nbsp;V, hard off), following the dead VBUS node without one. That
node is not floating — R19/R20 pin it under 0.65&nbsp;V even against R18&rsquo;s
backfeed — so Vgs is &minus;2.4&nbsp;V at a 3.0&nbsp;V cell and Q2 is fully on.</p>

<p><b>This retires the R8 rework rather than performing it.</b> 22k already gives
40.9&nbsp;mA, which is exactly the fitted RJD2032C1&rsquo;s rated 40&nbsp;mA, and
the reason 15k was tempting is gone. So is the hazard that blocked it: with the
system off the cell, the full program current reaches the cell in
<i>either</i> switch position.</p>

<p>What else falls out — DONE can finally assert (the cell&rsquo;s current
actually tapers to ITERM now), VBSENSE reads a true <i>unloaded</i> cell while
charging, the ring lights on a dead cell, and the board runs with no cell fitted
at all.</p>

<p><b>The cost is a level shifter, and it is not optional.</b> SK6805 VIH is
0.7&times;VDD; on the cell that peaked at 2.94&nbsp;V so a 3.3&nbsp;V pad drove
the ring directly, but on VSYS it is 3.29&nbsp;V typical and 3.5&nbsp;V at the
5.25&nbsp;V USB ceiling. Q3 (BSS138W) is an open-drain inverter with R23
1k&nbsp;pulling LED_D0 up to VLED itself, so the swing is a full VLED rail
whatever VLED is. Only pixel&nbsp;1 needs it — every downstream DI is driven by
the previous DO. Diode-dropping VSYS into the LED window instead does
<i>not</i> work: two Schottkys land at 3.8&nbsp;V at the low corner (under the
floor) and 4.65&nbsp;V at the high one (VIH 3.26&nbsp;V, still failing). The
window is narrower than the corners, so the level has to move, not the rail.</p>

<p class="warn">⚠ <b>Firmware pairing, rev-2 boards only.</b> The stage inverts,
so <code>main.cpp</code> needs
<code>gpio_set_outover(LED_DATA,&nbsp;GPIO_OVERRIDE_INVERT)</code>. The pad
override sits after the peripheral mux, so the NeoPixel PIO program is untouched.
<b>Do not flash it to a rev-1 board.</b> Idle is safe either way: PIO idle-low
&rarr; pad high &rarr; Q3 on &rarr; LED_D0 low, the reset level the ring wants,
and before the override is set VLED is off (R10 holds LED_EN low) so R23&rsquo;s
pull-up is dead and the line cannot float.</p>

<p>SW2 deliberately <i>stays</i> on VBATT. On VSYS the R11 divider would read a
constant 2.35&nbsp;V whenever a cable is in, saying nothing about either the cell
or the switch; on VBATT all four states stay separable with VBUS_SENSE as the
cable bit.</p>

<h4>Also in this commit</h4>
<ul>
<li><b>BT1&rsquo;s negative contact is now six solder bumps.</b> The first
assembled board would not hold the cell against the centre pad: 176 B.Cu track
endpoints sit within r9.5 of it, and 35&nbsp;µm of copper under 20&nbsp;µm of
mask stands ~25&nbsp;µm <i>proud</i> of a bare pad face, so the rigid coin rode
on soldermask and never touched copper. Hand-tinning fixed it on the bench.
Baking that in is not &ldquo;add paste to the Ø8 pad&rdquo; — molten solder on
one big bare opening has nothing to hold it and levels out ~8&nbsp;µm thick.
Solder only stands proud if mask dams it. So the centre contact becomes a ring of
six mask-defined bumps, Ø1.2 openings on r2.8 pasted 1:1, over the same Ø8 copper
left mask-covered. At a 0.12&nbsp;mm stencil each holds ~0.07&nbsp;mm³ and domes
~0.12&nbsp;mm, i.e. ~65&nbsp;µm clear of the mask plane. Six on a ring because
three points define the plane the coin sits on and a single central dome would
let it rock. The copper does not move, so nothing the router already solved
changes.</li>
<li><b>R19/R20 are placed for the first time.</b> The VBUS sense divider reached
the netlist in <code>619042b</code> but never the board, so both sat at the
origin and the relaxer scattered them through the MCU decaps — that is where the
C2/C20/C74/LED45 courtyard overlaps came from.</li>
<li><b><code>tools/scan_spot.py</code></b>, the pad-polygon placement scanner the
whole placement came out of, and <code>tools/pad_preview.py</code>, which exists
because rotation sense is <i>negated</i> on the back side and the only safe way
to pick an orientation is to place it and read the pads back. The scan found the
front has exactly <b>six</b> legal SC-70 spots board-wide, all in the south-west
— which is why Q2 lives on the back annulus and Q3 took the best of the six.</li>
<li><b>A lesson worth keeping.</b> Locked pre-route geometry <i>moves</i> with
the footprints it is derived from. R22&rsquo;s coarse-scan spot was legal when
scanned, but the relaxer settles C16 a hair differently once the new parts are
fixed, and <code>route.py</code> anchors the locked CHRG_DONE landing loop to
C16 — the pad ended up 0.1227&nbsp;mm from that track against a 0.127 rule.
Re-scanned at 0.05&nbsp;mm, 70&nbsp;µm east. All six new passives are now exempt
from the relaxer for the same reason, and the DRC gate is re-run after every
placement change.</li>
</ul>
<p class="note">Routed the same day — <code>bdc87fc</code>, 0 DRC errors with five
nets still open. See the newest entry at the top; the live renders and layer
stack below are that board, not this placement.</p>
""",
        media=[("render_place_top.png",
                "placement preview front — Q3/R23 west of the MCU, D3/C29/R21 "
                "in the east pocket", True),
               ("render_place_bottom.png",
                "placement preview back — Q2 on the south-east shoulder, "
                "mirroring D2/R17", True)],
    ),
    dict(
        date="2026-08-28", sha="02ffecf", tags=["case"],
        title="Case: flush LED pockets, six chonky clip tabs (three a side)",
        lede="Every LED gets the same flush conical pocket, and the rim drops "
             "from ten 4&nbsp;mm stations to six chunky tabs.",
        body="""
<p>The diffuser floor loses the eight per-LED bosses over the inner ring; all 45
pockets are now identical cones (over the raised mid floor the cone just emerges
shallower, same ceiling everywhere).</p>
<p>Stations can override lip depth: the 0° front tab runs 0.65&nbsp;mm so it
clears the BT1 clip-arm courtyard corners at every probe depth. All station
margins positive, halves stay single valid solids, plug corridor clear. Rear
engagement up 9.7&nbsp;&rarr;&nbsp;14.5&nbsp;mm³, front
24.0&nbsp;&rarr;&nbsp;17.1&nbsp;mm³.</p>
<p><a href="case/preview/">all case views + fit report &rarr;</a></p>
""",
        media=[("case/preview/assembly-front.png",
                "assembled, front — the diffuser face", False),
               ("case/preview/section-y.png",
                "section: pockets under the LEDs, cell inside the cup", False)],
    ),
    dict(
        date="2026-08-28", sha="00b48b4", tags=["tooling", "bench"],
        title="Bench tools that were living untracked",
        lede="A live charge plotter, the R8 rework diagrams, and a host USB "
             "controller reset.",
        body="""
<ul>
<li><code>tools/charge_monitor.py</code> plots live VBATT against the two lines
that decide whether the board works: 3.70&nbsp;V (SK6805-EC10 minimum VDD) and
4.20&nbsp;V full. Strictly read-only — the firmware&rsquo;s command handler takes
<code>X</code> to wipe stored sessions, so it never writes a byte to the port.</li>
<li><code>scripts/gen_rework_svg.py</code> draws the rework into
<code>out/rework/</code>, reading the <b>ordered</b> revision straight out of git
rather than the working tree — the boards in hand are that revision, and
<code>out/earring.kicad_pcb</code> can legitimately be mid-generation with every
footprint stacked at one point.</li>
<li><code>tools/reset_usb.sh</code> unbinds and rebinds one xhci PCI function to
power-cycle the port the earring flashes through. Every port on the controller
blips for a couple of seconds, keyboard included — which is exactly why it is a
script and not something to type mid-way.</li>
</ul>
""",
        media=[],
    ),
    dict(
        date="2026-08-28", sha="152c3ca", tags=["firmware"],
        title="Firmware: blink the charge arc, and wait for C21 before "
              "believing the ADC",
        lede="The dithered assembling arc banded on hardware; it now blinks 1&nbsp;s "
             "on / 4&nbsp;s off, which also hands four fifths of the LED load "
             "back to the charge budget.",
        body="""
<p>The arc used to dither spatially — every 50&nbsp;ms a random fraction of the
dark arc LEDs snapped on — to hold one solid colour at counts too small to fade
through. On hardware it shimmered rather than reading as a fill. It now simply
blinks, and the measurement moves to the falling edge: rail down first, then
sample, so there is no LED load on the cell while measuring.</p>
<p><b>Boot sensing was reading garbage.</b> VBSENSE comes off a 1M:1M divider
with C21 = 100&nbsp;nF on the bottom leg, so it rises with &tau;&nbsp;=&nbsp;50&nbsp;ms
from an <i>empty</i> cap at power-on. A 4.0&nbsp;V cell (68%) decoded as 0–4%
anywhere in the 60–100&nbsp;ms window, and under ~55&nbsp;ms VBSENSE has not even
cleared the 1.27&nbsp;V band edge, so the switch position itself decoded wrong.
Boot now waits to 400&nbsp;ms (8&tau;, residual under 0.1%) and a separate
8-sample warmup throws away the ADC&rsquo;s first conversions — 500k source
impedance is far above what the RP2350&rsquo;s sample-and-hold wants.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-28", sha="619042b", tags=["hardware"],
        title="Rev 3: USB-or-switch LDO enable, VBUS presence sense",
        lede="Two gaps closed, both about knowing the board is plugged in.",
        body="""
<p>SW2 no longer drives the LDO enable directly. Its common becomes SW_ON, and D2
(BAT54SW, dual <i>series</i> Schottky) ORs two sources into PWR_EN: diode 1
passes SW_ON, diode 2 clamps EN to VBATT&nbsp;+&nbsp;Vf. <b>The clamp is
mandatory</b> — the NCP730&rsquo;s abs-max V_EN is (V_IN&nbsp;+&nbsp;0.3), not an
independent rating, so a bare feed from 5&nbsp;V VBUS would violate it
essentially always. Net effect: USB boots the chip with the switch off, so
plugged-in charging can be indicated.</p>
<p>R19/R20 tap VBUS 10k:10k into ADC1. CHRG and DONE cannot tell
&ldquo;unplugged&rdquo; from &ldquo;plugged in and <i>finished</i>&rdquo; — when
the charger terminates, both open-drain pins release and the indicator loses its
only evidence a cable is attached. Seen on the bench Aug&nbsp;25: cell full at
4.11&nbsp;V, USB in, chrg=0 done=0, firmware correctly but uselessly back on the
drip show. The low impedance is the design, not an oversight: with SW2 on and no
USB, PWR_EN backfeeds through R18 and floats the dead VBUS node, and a
high-impedance divider would read that as plugged in.</p>
<p>Placement of D2/R17/R18 came from the first full-board scan against pad
<i>copper</i>, not just courtyards — SW2&rsquo;s pads stick out past its
courtyard polygon, and J1&rsquo;s tie pads report <code>GetSize</code>
0.01&times;0.01 while spanning 1.5&times;1.4&nbsp;mm of real copper, so
size-based scans sail straight through them.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-28", sha="3528329", tags=["case"],
        title="Generated TPU clip-on shell — LED diffuser + battery cup",
        lede="Two flexible halves, generated from the <b>ordered</b> board "
             "(43eadc1) read straight out of git — outline, all 45 LED "
             "positions, every courtyard.",
        body="""
<p>Front half is a diffuser: a tapered pocket over every LED, 1.10&nbsp;mm of TPU
between pocket ceiling and a smooth flat outer face. BOOTSEL presses through a
0.70&nbsp;mm membrane rather than a hole. Rear half is a closed cup over the coin
cell and clip — the short-protection half.</p>
<p>Each half locks to the <i>board</i> only, so the rims interleave as a plain
castellation with nothing protruding. The tip is left clear for the mount plug
(the earring hangs from a loop soldered to a male USB-C plug that stays in J1),
and SW2 gets an open thumb scoop in the left flank. Both halves print
outer-face-down with no supports.</p>
<p><b>Also fixed here:</b> <code>outline.segs()</code> had the arc sweep as
2&pi;&nbsp;&minus;&nbsp;2&middot;ang where it should be &pi;&nbsp;+&nbsp;2&middot;ang.
That overstated the perimeter by 12.2&nbsp;mm and made the sampled polygon
self-intersect on the left flank, so <code>inside()</code> answered wrongly there
and LED38 lost its floor-drop boss.</p>
""",
        media=[("case/preview/front-inner-iso.png",
                "front half inside: 45 LED pockets, seat ledge, clip stations",
                False),
               ("case/preview/rear-inner-iso.png",
                "rear cup inside: cell pad, ramped seat ledge, clip fingers",
                False)],
    ),
    dict(
        date="2026-08-27", sha=None, tags=["bench", "hardware"],
        title="R8 charge-current rework proposed — and blocked",
        lede="22k&nbsp;&rarr;&nbsp;15k to get the cell more than ~6&nbsp;mA. "
             "Blocked by SW2-off, and now retired outright by the Aug&nbsp;31 "
             "power path.",
        body="""
<p>The ordered boards wire the switch straight to the LDO enable, so switched
<b>off</b> the cell takes the whole program current: 22k&nbsp;=&nbsp;1.0C,
15k&nbsp;=&nbsp;1.5C on a cell with no published maximum. The rev-2 R17/R18/D2
network that would have fixed that is not on the fabricated boards.</p>
<p>I_sys&nbsp;&asymp;&nbsp;17&nbsp;mA was derived by cancelling dQ/dV against two
measured charge runs. <b>Superseded:</b> splitting VBATT from VSYS removes the
shared-node problem entirely, so 22k stays.</p>
<p><a href="rework/">value, budget + rework diagram &rarr;</a></p>
""",
        media=[],
    ),
    dict(
        date="2026-08-27", sha=None, tags=["bench", "bom"],
        title="The fitted cell is an RJD2032C1, not the LIR2032 the schematic names",
        lede="85&nbsp;mAh NMC, 3.6&nbsp;mm thick, flat 40&nbsp;mA charge with no "
             "published maximum.",
        body="""
<p>22k on R8 already gives 40.9&nbsp;mA, i.e. the cell&rsquo;s full rated charge
current — which is what killed the 15k rework. Internal resistance is
&le;700&nbsp;m&Omega;, so the firmware&rsquo;s 150&nbsp;mV IR correction in
<code>chargePct</code> is roughly 5&times; too big; on the rev-2 power path the
cell is unloaded while charging anyway and the correction should drop to the
charger&rsquo;s own ~28&nbsp;mV.</p>
<p>Still to be reconciled in <code>design.yaml</code> and
<code>circuit.py</code>&rsquo;s BT1 value.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-27", sha=None, tags=["bench"],
        title="Why the ring was dark: VLED under the SK6805 floor",
        lede="MCU, USB, IMU, flash, charger and ADC all verified <b>good</b> "
             "while the board showed nothing at all.",
        body="""
<p>SK6805-EC10 needs 3.7&nbsp;V minimum VDD. VLED is VBATT through the TPS22913,
and the cell was living at 3.35–3.6&nbsp;V — so the ring could not light, and no
firmware change would have helped. <b>Check VBATT&nbsp;&ge;&nbsp;3.7&nbsp;V
before blaming firmware or the ring.</b> This is the finding the Aug&nbsp;31
power path is the answer to.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-25", sha="d5b0cfa", tags=["firmware"],
        title="Firmware: halve the power draw, rebuild the charge indicator, log wear",
        lede="Battery measured ~1&nbsp;h. Three levers: 50&nbsp;MHz, a show/nap "
             "duty cycle with VLED cut, and a lazier pattern.",
        body="""
<p>clk_sys 150&nbsp;&rarr;&nbsp;50&nbsp;MHz (the awake MCU was ~20&nbsp;mA of the
budget), and the show now plays ~12&nbsp;s episodes separated by naps with VLED
cut — 45 idle SK6805 draw ~13.5&nbsp;mA even showing black.</p>
<p>Nap length is tiered by activity, calibrated from a logged stand/walk/dance
session worn on the ear. The existing motion envelope separates all three with
<b>no overlap</b> (standing 25–30, walking 84–159 p10–p90, dancing 491–925), so
one filtered value drives the rhythm: 25&nbsp;s still / 5&nbsp;s walking /
2&nbsp;s dancing. Walking had been napped through ~50% of the time — exactly when
the earring is seen.</p>
<p><a href="wear/">wear log + activity calibration &rarr;</a></p>
""",
        media=[],
    ),
    dict(
        date="2026-08-25", sha="ff704e1", tags=["bench", "milestone"],
        title="Board alive: USB, IMU, LEDs and charger all pass",
        lede="Fixed by tinning the centre pad and fitting a <i>charged</i> cell.",
        body="""
<p>Gotchas worth keeping: a post-flash warm reboot needs an SW2 power cycle; with
a battery fitted a USB replug is <b>not</b> a reset; and the flaky-USB
root cause was a discharged cell, so swap in a charged one before blaming a
board. Test firmware lives in <code>firmware/</code>.</p>
<p><a href="probe/">multimeter probe map &rarr;</a></p>
""",
        media=[],
    ),
    dict(
        date="2026-08-25", sha="81e2a0e", tags=["hardware", "bom"],
        title="Rev 2 electronics: external flash, MYOUNG clip, ambient light sensor",
        lede="RP2350A + external W25Q16JV, BT1 swapped to the flat-foot MYOUNG "
             "MY-2032-12-R, and an ALS-PT19-315C on ADC0 by the heart.",
        body="""
<p>The battery clip swap matters most: the ordered rev&rsquo;s BT1 lacks the
Ø3.5/3.6 thru-holes the QIJEY clip needs, so the fabricated boards cannot take
that part at all. Generator drift against the ordered board was also fixed here —
fresh builds had become unroutable — along with a shipped-truth via corridor and
straggler assist vias in <code>route.py</code>.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-08", sha="43eadc1", tags=["milestone"],
        title="ORDER PLACED at JLCPCB",
        lede="Board fully routed, DRC 0/0. <b>This revision is the hardware in "
             "hand.</b>",
        body="""
<p>Every bench page — the rework diagrams, the TPU case — reads
<code>43eadc1</code> straight out of git rather than the working tree, because
the working tree has been on rev 2 and then rev 3 ever since and is not the board
that exists. A worktree of it is checked out at
<code>~/pcb/simple_earring_shipped</code>.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-06", sha="3543adf", tags=["layout", "hardware"],
        title="Datasheet review of every chip, then a layout fix pass",
        lede="Two fatal pinout bugs: the IMU&rsquo;s pins 12/13/14 and the "
             "BOOTSEL switch pairing were both wrong.",
        body="""
<p>Lesson: verify pin maps against primary datasheets, not against symbols. The
fix pass that followed healed the 3V3 feed necks, stitched the pours and
chamfered the corners, landing at DRC 0/0.</p>
<p><a href="review/">layout review &rarr;</a> &nbsp;·&nbsp;
<a href="review/fixes.html">fix pass + diffs &rarr;</a></p>
""",
        media=[],
    ),
    dict(
        date="2026-08-05", sha="0513be3", tags=["layout", "bom"],
        title="4-layer stackup, part swaps, generated schematic",
        lede="Dropped 6 layers to 4 for JLC lead time, and made the schematic a "
             "generated artifact rather than a hand-drawn one.",
        body="""
<p>Part churn along the way, all of it from stock or package checks: RP2354A went
OOS so the design became RP2350A + external QSPI flash; the TBA-C1010MB LED went
OOS and became the SK6805-EC10; the crystal became the RP2350-recommended
ABM8-272-T3; and C25804 turned out to be an <b>0603 on an 0402 land</b> — check
package, not just value.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-03", sha="25be6fd", tags=["tooling"],
        title="This dashboard, the layer-stack viewer, and the 3D board",
        lede="Generated from <code>render.py</code>, served from "
             "<code>out/</code>, auto-refreshing every 15&nbsp;s.",
        body="""
<p>The 3D viewer uses TrackballControls rather than Orbit so the board can be
tumbled continuously end over end with no pole clamp.</p>
""",
        media=[],
    ),
    dict(
        date="2026-08-02", sha="f2bb985", tags=["milestone", "tooling"],
        title="Generated-PCB framework: first fully-routed DRC-clean build",
        lede="Outline, placement, routing, DRC, renders and fab exports, all "
             "from <code>design.yaml</code> + <code>circuit.py</code>.",
        body="""
<p>The teardrop board, USB-C at the tip, perimeter LEDs and an insertion-safe
back followed within the same day.</p>
""",
        media=[],
    ),
]


def _feed_html():
    """Render FEED to HTML. Newest entry open, the rest collapsed."""
    from datetime import date as _date
    out = []
    for i, e in enumerate(FEED):
        y, m, d = (int(v) for v in e["date"].split("-"))
        stamp = _date(y, m, d).strftime("%b&nbsp;%-d")
        chips = "".join(
            f'<span class="tag" style="color:{TAGS.get(t, "#aaa")};'
            f'border-color:{TAGS.get(t, "#aaa")}44">{t}</span>'
            for t in e["tags"])
        sha = (f'<code class="sha">{e["sha"]}</code>' if e["sha"]
               else '<span class="sha nosha">bench</span>')
        figs = []
        for src, cap, live in e["media"]:
            cls = ' class="rf"' if live else ""
            figs.append(f'<figure><img{cls} src="{src}">'
                        f"<figcaption>{cap}</figcaption></figure>")
        media = f'<div class="row">{"".join(figs)}</div>' if figs else ""
        out.append(
            f'<li class="entry"><details{" open" if i == 0 else ""}>'
            f'<summary><span class="when">{stamp}</span>'
            f'<span class="head"><span class="title">{e["title"]}</span>'
            f'{chips}{sha}<span class="lede">{e["lede"]}</span></span>'
            f"</summary>"
            f'<div class="body">{e["body"]}{media}</div>'
            f"</details></li>")
    return "\n".join(out)


def _status_html():
    """A live line about the build the page is showing: what commit the tree
    is on, when the board file was last written, and the last DRC result.
    Read at render time — drc.json can legitimately be older than the board
    (render runs after drc, but a --only render does not), so both are
    stamped rather than presented as one truth."""
    import datetime
    import json
    bits = []
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%h\t%s"], cwd=ROOT,
            capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            sha, subj = r.stdout.strip().split("\t", 1)
            dirty = subprocess.run(
                ["git", "status", "--porcelain"], cwd=ROOT,
                capture_output=True, text=True).stdout.strip()
            flag = ' <span class="bad">+ uncommitted</span>' if dirty else ""
            bits.append(f'<b>HEAD</b> <code>{sha}</code> {subj}{flag}')
    except Exception:
        pass
    try:
        t = datetime.datetime.fromtimestamp(PCB.stat().st_mtime)
        bits.append(f'<b>board</b> written {t:%b %-d %H:%M}')
    except Exception:
        pass
    try:
        rep = ROOT / "out" / "drc.json"
        d = json.loads(rep.read_text())
        viol = d.get("violations", [])
        errs = sum(1 for v in viol if v["severity"] == "error")
        unconn = len(d.get("unconnected_items", []))
        t = datetime.datetime.fromtimestamp(rep.stat().st_mtime)
        # a report older than the board describes a DIFFERENT board, and a
        # green "0 errors, 0 unconnected" against a freshly re-placed and
        # not-yet-routed .kicad_pcb is worse than no number at all
        stale = rep.stat().st_mtime < PCB.stat().st_mtime
        cls = "bad" if (stale or errs or unconn) else "good"
        note = " — STALE, board is newer" if stale else ""
        bits.append(
            f'<b>DRC</b> <span class="{cls}">{errs} errors, '
            f"{unconn} unconnected{note}</span> "
            f'<span class="dim">({len(viol)} total, {t:%b %-d %H:%M})</span>')
    except Exception:
        bits.append('<b>DRC</b> <span class="dim">no report yet</span>')
    return " &nbsp;·&nbsp; ".join(bits)


INDEX_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>simple_earring</title>
<style>
  :root { --bg:#1a1a1e; --card:#26262e; --line:#33333c; }
  body { background:var(--bg); color:#ddd; font-family:sans-serif; margin:0;
         padding:1rem 1rem 4rem; }
  a { color:#8bf; }
  h1 { font-size:1.15rem; font-weight:600; margin:0 0 .5rem; }
  h2 { font-size:.95rem; font-weight:600; color:#bbb; margin:1.8rem 0 .6rem;
       border-bottom:1px solid var(--line); padding-bottom:.3rem; }
  h4 { font-size:.85rem; color:#cfcfd6; margin:1rem 0 .35rem; }
  .row { display:flex; flex-wrap:wrap; gap:1rem; }
  figure { margin:0; }
  figcaption { text-align:center; padding:.3rem; color:#aaa; font-size:.85rem;
               max-width:min(46vw,900px); }
  img { max-width:min(46vw,900px); height:auto; border-radius:8px;
        background:var(--card); }
  #ts { color:#777; font-size:.8rem; font-weight:400; }
  .nav { display:flex; flex-wrap:wrap; gap:.45rem; font-size:.85rem;
         margin:.5rem 0 .8rem; }
  .nav a { text-decoration:none; border:1px solid var(--line); border-radius:999px;
           padding:.18rem .6rem; background:var(--card); }
  .status { background:var(--card); border:1px solid var(--line);
            border-radius:8px; padding:.5rem .8rem; font-size:.85rem;
            color:#bbb; margin-bottom:.6rem; }
  .status .good { color:#8f8; } .status .bad { color:#f88; }
  .status .dim { color:#777; }

  /* ---- feed ---- */
  ol.feed { list-style:none; margin:0; padding:0; }
  .entry { border-left:2px solid var(--line); padding:0 0 0 .9rem;
           margin:0 0 .1rem; position:relative; }
  .entry::before { content:""; position:absolute; left:-5px; top:.75rem;
                   width:8px; height:8px; border-radius:50%;
                   background:#4a4a56; }
  .entry:first-child::before { background:#8f8; }
  .entry summary { cursor:pointer; list-style:none; padding:.5rem 0;
                   display:flex; gap:.7rem; align-items:baseline; }
  .entry summary::-webkit-details-marker { display:none; }
  .entry summary:hover .title { color:#fff; }
  .when { color:#777; font-size:.78rem; white-space:nowrap; min-width:3.6rem;
          font-variant-numeric:tabular-nums; padding-top:.1rem; }
  .head { display:flex; flex-wrap:wrap; gap:.35rem .5rem; align-items:baseline; }
  .title { font-size:.95rem; font-weight:600; color:#e2e2e8; }
  .tag { font-size:.68rem; text-transform:uppercase; letter-spacing:.04em;
         border:1px solid; border-radius:999px; padding:.02rem .4rem; }
  .sha { font-size:.7rem; color:#777; background:#222228; border-radius:4px;
         padding:.05rem .3rem; }
  .sha.nosha { font-style:italic; background:none; }
  .lede { flex-basis:100%; color:#9a9aa4; font-size:.85rem; line-height:1.45; }
  details[open] .lede { color:#b6b6c0; }
  /* 4.3rem = .when's 3.6rem column + summary's .7rem gap, so the body
     lines up under the title rather than under the date. The 78ch measure
     goes on the text children, not on .body itself, so a media row can
     still lay two renders out side by side. */
  .entry .body { font-size:.88rem; line-height:1.6; color:#c4c4cc;
                 padding:.1rem 0 1.4rem 4.3rem; }
  .entry .body > p, .entry .body > ul, .entry .body > h4,
  .entry .body > pre, .entry .body > div:not(.row) { max-width:78ch; }
  .entry .body p { margin:.55rem 0; }
  .entry .body ul { margin:.5rem 0; padding-left:1.1rem; }
  .entry .body li { margin:.4rem 0; }
  /* narrower than the standalone renders below: the feed body is already
     indented 4.3rem, and at the shared min(46vw,900px) a pair overflows
     that column by ~20px and wraps to one per line */
  .entry .body .row { margin-top:.9rem; }
  .entry .body img, .entry .body figcaption { max-width:min(38vw,620px); }
  .entry .body code { background:#222228; border-radius:3px; padding:0 .2rem;
                      font-size:.9em; }
  pre.art { background:#202026; border:1px solid var(--line); border-radius:6px;
            padding:.6rem .8rem; font-size:.78rem; line-height:1.45;
            color:#a9c8a9; overflow-x:auto; }
  .warn { background:#2a2119; border-left:3px solid #d9a441; border-radius:4px;
          padding:.5rem .7rem; }
  .note { background:#1e2429; border-left:3px solid #5a8fb5; border-radius:4px;
          padding:.5rem .7rem; }

  /* ---- layer stack viewer ---- */
  #viewer { display:flex; gap:1rem; align-items:flex-start; }
  #panel { padding:12px; min-width:210px; background:var(--card);
           border-radius:8px; }
  .lay { display:flex; align-items:center; gap:8px; padding:5px 2px; }
  .lay .sw { width:14px; height:14px; border-radius:3px; }
  #stack { position:relative; }
  #stack img { position:absolute; inset:0; width:100%; height:100%;
               max-width:none; pointer-events:none; border-radius:0;
               background:none; }
  #stack img.base { position:relative; display:block; width:auto; height:auto;
                    max-width:min(66vw,1100px); background:#fff;
                    border-radius:8px; }
  label { user-select:none; }
  input[type=range] { width:100%; }
  .hint { color:#888; font-size:.75rem; margin-top:10px; }
</style></head><body>

<h1>simple_earring <span id="ts"></span></h1>
<div class="nav">
  <a href="#feed">updates ↓</a>
  <a href="#outputs">live outputs ↓</a>
  <a href="case/preview/" style="color:#c9f">TPU case</a>
  <a href="rework/" style="color:#a88">R8 rework (retired)</a>
  <a href="wear/" style="color:#9cf">wear log</a>
  <a href="probe/" style="color:#f88">probe map</a>
  <a href="review/" style="color:#fc6">layout review</a>
  <a href="review/fixes.html" style="color:#8f8">fix pass</a>
  <a href="earring.svg">schematic SVG</a>
  <a href="earring-schematic.pdf">PDF</a>
</div>
<div class="status">{{STATUS}}</div>

<h2 id="feed">Updates</h2>
<ol class="feed">
{{FEED}}
</ol>

<h2 id="outputs">Live outputs</h2>
<div class="hint" style="margin:0 0 .7rem">
  regenerated by <code>scripts/render.py</code> on every build; images on this
  page auto-refresh every 15&nbsp;s</div>
<div class="row">
  <figure><img class="rf" id="ptop" src="render_place_top.png"><figcaption>placement preview front (unrouted, updates right after place)</figcaption></figure>
  <figure><img class="rf" id="pbot" src="render_place_bottom.png"><figcaption>placement preview back (unrouted)</figcaption></figure>
</div>
<div class="row">
  <figure><img class="rf" id="rtop" src="render_top.png"><figcaption>front, routed (MCU + LED ring)</figcaption></figure>
  <figure><img class="rf" id="rbot" src="render_bottom.png"><figcaption>back, routed (battery clip)</figcaption></figure>
</div>
<div class="row">
  <figure><img class="rf" id="laytop" src="layout_top.png"><figcaption>layout top (F.Cu over In1/In2/B.Cu)</figcaption></figure>
  <figure><img class="rf" id="laybot" src="layout_bottom.png"><figcaption>layout bottom, mirrored (B.Cu over In2/In1/F.Cu)</figcaption></figure>
</div>

<h2>Copper layers</h2>
<div class="row">
  <figure><img class="rf" id="grid" src="layout_layers.png" style="max-width:min(92vw,1400px)"><figcaption>individual copper layers (top view)</figcaption></figure>
</div>

<h2>Layer stack viewer</h2>
<div id="viewer">
  <div id="panel">
    <div id="layers"></div>
    <div style="margin-top:12px">others opacity
      <input type="range" id="dim" min="0" max="100" value="25">
    </div>
    <div class="hint">radio = selected layer (always opaque)<br>
         checkbox = layer visible at all<br>
         slider = opacity of visible, unselected layers<br>
         all layers drawn from the top, unmirrored</div>
  </div>
  <div id="stack">
    <img class="base rf" id="img_edge" src="layer_edge.png">
{{IMGS}}
  </div>
</div>
<script>
const LAYERS = {{LAYERS_JS}};
const dim = document.getElementById('dim');
const box = document.getElementById('layers');
const state = {sel: LAYERS[0][1], vis: Object.fromEntries(
    LAYERS.map(l => [l[1], true]))};
for (const [name, slug, color] of LAYERS) {
  const row = document.createElement('div');
  row.className = 'lay';
  row.innerHTML = `<input type="radio" name="sel" id="r_${slug}">` +
    `<input type="checkbox" id="v_${slug}" checked>` +
    `<span class="sw" style="background:${color}"></span>` +
    `<label for="r_${slug}">${name}</label>`;
  box.appendChild(row);
  row.querySelector(`#r_${slug}`).onchange = () => { state.sel = slug; apply(); };
  row.querySelector(`#v_${slug}`).onchange = e => {
    state.vis[slug] = e.target.checked; apply(); };
}
document.getElementById('r_' + state.sel).checked = true;
dim.oninput = apply;
function apply() {
  for (const [, slug] of LAYERS) {
    const img = document.getElementById('img_' + slug);
    img.style.display = state.vis[slug] ? '' : 'none';
    img.style.opacity = (slug === state.sel) ? 1 : dim.value / 100;
  }
}
apply();
// only images the build regenerates carry class="rf"; historical shots in
// collapsed feed entries stay static so expanding one is not a reload storm
function refresh() {
  const t = Date.now();
  for (const img of document.querySelectorAll('img.rf')) {
    img.src = img.src.split('?')[0] + '?' + t;
  }
  document.getElementById('ts').textContent =
    '(auto-refresh ' + new Date().toLocaleTimeString() + ')';
}
setInterval(refresh, 15000);
refresh();
</script>

<h2>Interactive 3D board</h2>
<div id="three" style="width:min(94vw,1400px);height:640px;background:#222228;
     border-radius:8px;overflow:hidden"></div>
<div class="hint" style="color:#888;font-size:.75rem;margin-top:6px">
  drag = orbit, wheel = zoom, right-drag = pan (board.glb regenerates each build)</div>
<script type="importmap">
{"imports": {"three": "./vendor/three.module.js"}}
</script>
<script type="module">
import * as THREE from 'three';
import { TrackballControls } from './vendor/TrackballControls.js';
import { GLTFLoader } from './vendor/GLTFLoader.js';
const el = document.getElementById('three');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x222228);
const cam = new THREE.PerspectiveCamera(
    40, el.clientWidth / el.clientHeight, 0.001, 10);
const renderer = new THREE.WebGLRenderer({antialias: true});
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(el.clientWidth, el.clientHeight);
el.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff, 1.0));
const d1 = new THREE.DirectionalLight(0xffffff, 2.2);
d1.position.set(1, 1, 2); scene.add(d1);
const d2 = new THREE.DirectionalLight(0xffffff, 1.0);
d2.position.set(-1, -0.5, -2); scene.add(d2);
// TrackballControls (not Orbit): no pole clamp, so the board can be
// tumbled continuously end over end
const controls = new TrackballControls(cam, renderer.domElement);
controls.rotateSpeed = 4.0;
controls.zoomSpeed = 1.4;
controls.panSpeed = 0.6;
controls.dynamicDampingFactor = 0.12;
new GLTFLoader().load('board.glb?' + Date.now(), g => {
  const obj = g.scene;
  const box = new THREE.Box3().setFromObject(obj);
  obj.position.sub(box.getCenter(new THREE.Vector3()));
  scene.add(obj);
  const r = box.getSize(new THREE.Vector3()).length();
  cam.position.set(0, r * 0.55, r * 0.8);
  cam.near = r / 1000; cam.far = r * 20;
  cam.updateProjectionMatrix();
  controls.update();
});
(function loop() {
  requestAnimationFrame(loop);
  controls.update();
  renderer.render(scene, cam);
})();
window.addEventListener('resize', () => {
  cam.aspect = el.clientWidth / el.clientHeight;
  cam.updateProjectionMatrix();
  renderer.setSize(el.clientWidth, el.clientHeight);
  controls.handleResize();
});
</script>
</body></html>
"""


def main():
    ok = True
    # --index-only: rewrite out/index.html from the current PNGs and FEED,
    # touching nothing else. Safe to run while a build holds the board.
    if "--index-only" in sys.argv:
        write_index()
        sys.exit(0)
    # --placement: quick post-place preview (no routing yet) -> separate
    # files so the routed renders aren't clobbered mid-build
    placement = "--placement" in sys.argv
    prefix = "render_place_" if placement else "render_"
    for side in ("top", "bottom"):
        out = ROOT / "out" / f"{prefix}{side}.png"
        r = subprocess.run(
            ["kicad-cli", "pcb", "render", "--side", side,
             "--quality", "high", "--zoom", "0.9",
             "-o", str(out), str(PCB)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            print(f"wrote {out}")
    if placement:
        sys.exit(0 if ok else 1)
    # layout views: kicad-cli only exports vector formats for layer views,
    # so export SVG then rasterize to a PNG matching the 3D render size
    # (board centered on white); the intermediate SVG is removed
    try:
        from PIL import Image
        size = Image.open(ROOT / "out" / f"{prefix}top.png").size
    except Exception:
        size = (1568, 872)
    for side, (layers, mirror) in LAYOUT_VIEWS.items():
        svg = ROOT / "out" / f"layout_{side}.svg"
        cmd = ["kicad-cli", "pcb", "export", "svg", "--mode-single",
               "--layers", layers, "--page-size-mode", "2",
               "--exclude-drawing-sheet", "-o", str(svg), str(PCB)]
        if mirror:
            cmd.insert(cmd.index("-o"), "--mirror")
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
            continue
        out = ROOT / "out" / f"layout_{side}.png"
        wh = f"{size[0]}x{size[1]}"
        r = subprocess.run(
            ["magick", "-density", "600", "-background", "white",
             str(svg), "-resize", wh, "-gravity", "center",
             "-extent", wh, "-alpha", "remove", "-alpha", "off",
             "-depth", "8", str(out)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            svg.unlink()
            print(f"wrote {out}")

    # ---- individual copper layers: transparent PNGs on the shared canvas
    # (page-size-mode 2 crops every export to the board bbox, so all
    # layers land in register), then a labeled 2x2 grid + stack viewer
    wh = f"{size[0]}x{size[1]}"
    for name, slug in LAYER_STACK + [("Edge.Cuts", "edge")]:
        svg = ROOT / "out" / f"layer_{slug}.svg"
        r = subprocess.run(
            ["kicad-cli", "pcb", "export", "svg", "--mode-single",
             "--layers", name, "--page-size-mode", "2",
             "--exclude-drawing-sheet", "-o", str(svg), str(PCB)],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
            continue
        out = ROOT / "out" / f"layer_{slug}.png"
        r = subprocess.run(
            ["magick", "-density", "600", "-background", "none",
             str(svg), "-resize", wh, "-gravity", "center",
             "-extent", wh, f"png32:{out}"],
            capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout, r.stderr)
            ok = False
        else:
            svg.unlink()
            print(f"wrote {out}")

    try:
        from PIL import Image, ImageDraw
        edge = Image.open(ROOT / "out" / "layer_edge.png").convert("RGBA")
        tw, th = size[0] // 2, size[1] // 2
        rows = (len(LAYER_STACK) + 1) // 2
        grid = Image.new("RGB", (tw * 2, th * rows), "white")
        draw = ImageDraw.Draw(grid)
        try:
            from PIL import ImageFont
            font = ImageFont.load_default(size=24)
        except Exception:
            font = None
        for i, (name, slug) in enumerate(LAYER_STACK):
            tile = Image.new("RGBA", size, "white")
            tile.alpha_composite(edge)
            tile.alpha_composite(
                Image.open(ROOT / "out" / f"layer_{slug}.png").convert("RGBA"))
            tile = tile.resize((tw, th), Image.LANCZOS).convert("RGB")
            x, y = (i % 2) * tw, (i // 2) * th
            grid.paste(tile, (x, y))
            draw.text((x + 10, y + 8), name, fill="#222", font=font)
        gout = ROOT / "out" / "layout_layers.png"
        grid.save(gout)
        print(f"wrote {gout}")
    except Exception as e:
        print(f"layer grid failed: {e}")
        ok = False

    # interactive 3D: board GLB + vendored three.js for the page viewer
    r = subprocess.run(
        ["kicad-cli", "pcb", "export", "glb", "-f", "--subst-models",
         "--include-tracks", "--include-pads", "--include-zones",
         "--include-silkscreen", "--include-soldermask",
         "-o", str(ROOT / "out" / "board.glb"), str(PCB)],
        capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        ok = False
    else:
        print(f"wrote {ROOT / 'out' / 'board.glb'}")
    write_index()
    sys.exit(0 if ok else 1)


def write_index():
    """The dashboard: one page served from out/ (:8618), auto-refreshing,
    with the update feed, the copper-stack viewer and the 3D board.

    Split out so `render.py --index-only` can rewrite it in a fraction of a
    second without touching the .kicad_pcb — which matters because editing
    FEED is a text edit, and a full render is minutes of kicad-cli that also
    cannot run while route.py holds the board file."""
    # swatches: sampled from each exported layer PNG so they always match
    # kicad-cli's theme, whatever the layer count
    def swatch(slug):
        try:
            from PIL import Image
            im = Image.open(ROOT / "out" / f"layer_{slug}.png")
            im = im.convert("RGBA").resize((128, 128))
            counts = {}
            for r, g, b, a in im.getdata():
                if a > 200:
                    counts[(r, g, b)] = counts.get((r, g, b), 0) + 1
            if counts:
                r, g, b = max(counts, key=counts.get)
                return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            pass
        return "#888888"
    imgs = "\n".join(
        f'    <img class="rf" id="img_{slug}" src="layer_{slug}.png">'
        for _, slug in LAYER_STACK)
    layers_js = "[" + ", ".join(
        f'["{name}", "{slug}", "{swatch(slug)}"]'
        for name, slug in LAYER_STACK) + "]"
    import shutil
    shutil.copytree(ROOT / "web" / "vendor", ROOT / "out" / "vendor",
                    dirs_exist_ok=True)

    index = ROOT / "out" / "index.html"
    # placeholder substitution, not %-formatting: the feed is prose full of
    # percent signs ("20-50%", "+50% over spec") and every one of them would
    # have to be doubled
    page = INDEX_HTML
    for key, val in (("IMGS", imgs), ("LAYERS_JS", layers_js),
                     ("FEED", _feed_html()), ("STATUS", _status_html())):
        page = page.replace("{{%s}}" % key, val)
    index.write_text(page)
    print(f"wrote {index}")


if __name__ == "__main__":
    main()
