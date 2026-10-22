#!/usr/bin/env python3
"""Generate a readable, hand-laid-out .kicad_sch from circuit.py.

The board is generated from code, so the schematic is generated too — but
it is laid out the way a person would draw it, not dumped as a grid of
boxes with a net label on every pin:

  * Real symbols. R/C/L/crystal/switch/battery/test-point use the standard
    IEC/KiCad shapes; ICs are boxes whose pins are placed by FUNCTION
    (power on top, ground on the bottom, bus signals on the side that
    faces the part they talk to).
  * Functional blocks. Each block (USB front end, charger, LDO, LED load
    switch, MCU, QSPI flash, crystal, VREG, IMU, LED ring) is drawn as a
    unit inside a dashed frame with a title, and the parts inside it are
    DIRECTLY WIRED to each other.
  * Rails are power symbols (GND / 3V3 / VBATT / VLED / VBUS / VDD_CORE).
    That is the normal idiom and it is what keeps power grouped instead of
    smeared across the sheet as text.
  * Labels only where a wire would have to travel: block-to-block signals
    (USB_DP/DM, IMU_SDA/SCL/INT1, LED_EN, LED_D0, CHRG, CHRG_DONE,
    VBSENSE) and the LED-chain row breaks. Short local runs also carry a
    small label so the net keeps the name circuit.py gave it, since the
    board is matched to the netlist by name.

Layout is hand-authored (positions are code, derived from each symbol's
real pin coordinates) — but the CONTENT is not: every net comes from
circuit.py, every pin is asserted against it, and the finished sheet is
re-imported through `kicad-cli sch export netlist` and diffed against
circuit.py. If the netlist changes and the layout doesn't, the build
fails loudly instead of drawing a lie.

Five checks keep the drawing honest, and all of them caught real bugs
while it was being written:
  - every pin in circuit.py must be drawn and wired (Book);
  - wires may only meet at declared junctions, and may not cross;
  - block frames may not overlap, and the paper is then cut to fit them
    (SCH_LAYOUT=1 prints each block's measured box, which is how the
    anchors in build_sheet() were chosen);
  - no reference, value or note may land on a wire or on other text —
    KiCad will happily draw an unreadable sheet, so check_text() refuses
    to emit one (SCH_LAYOUT=1 lists every clash);
  - the exported netlist must equal circuit.py's, net for net.

Output: out/earring.kicad_sch (+ .svg/.pdf). Regenerate with
`python3 build.py --only schematic`.
"""
import math
import os
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import GPIO, RP_PINS, build_circuit, load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "earring.kicad_sch"

# Deterministic UUIDs: same circuit -> same file, so git diffs show real
# changes instead of a fresh set of random ids every build.
NS = uuid.UUID("6f1c9d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f")
SHEET_UUID = uuid.uuid5(NS, "sheet")

FP_LIB = "earring"     # fp-lib-table nickname; gen_board.py writes the table
GRID = 2.54            # 100mil pin pitch
PINLEN = 2.54          # pin stub length on generated box symbols
# The sheet is cut to fit the drawing rather than the drawing padded out to
# a standard size: this is a review document read on screen, and a page with
# 30% empty margin just means everything is 30% smaller when you zoom to fit.
MARGIN = 12.0          # KiCad draws its border ~10mm in from the paper edge
TITLE_BLOCK = (120.0, 40.0)   # keep the bottom-right corner clear

FONT = "(effects (font (size 1.27 1.27)))"


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def q(v):
    """Round to the 1.27mm half-grid the whole sheet lives on."""
    return round(v, 4)


def eff(size=1.27, bold=False, just=None, hide=False, rot=None):
    b = " (bold yes)" if bold else ""
    # KiCad only knows left/right/top/bottom/mirror; horizontal centring is
    # the default, so "center" is spelled by leaving the token out.
    if just:
        just = " ".join(t for t in just.split() if t != "center")
    j = f" (justify {just})" if just else ""
    h = " (hide yes)" if hide else ""
    return f"(effects (font (size {size} {size}){b}){j}{h})"


# ---------------------------------------------------------------------------
# symbol geometry
# ---------------------------------------------------------------------------
def xf(px, py, rot):
    """Library coords (+y up) -> sheet offset (+y down) for a placed symbol."""
    x, y = px, -py
    if rot == 0:
        return x, y
    if rot == 90:
        return y, -x
    if rot == 180:
        return -x, -y
    if rot == 270:
        return -y, x
    raise ValueError(f"rotation {rot} not supported")


class SymDef:
    def __init__(self, name, style, pins, extent, sexpr, tb=(False, False)):
        self.name = name        # lib_id suffix
        self.style = style      # box | passive | power | point
        self.pins = pins        # num -> (px, py) connection anchor
        self.extent = extent    # (half_w, half_h) including pin stubs
        self.sexpr = sexpr
        self.has_top, self.has_bot = tb   # pins on the top / bottom edge


class Sch:
    def __init__(self):
        self.defs = {}          # name -> SymDef
        self.body = []
        self.refs = set()
        self.pwr_n = 0
        self.frames = []        # (x0, y0, x1, y1, title)
        self.head = []          # header text, outside every block frame
        self.wires = []         # (a, b) — split at junctions on render
        self.jpts = set()
        self.texts = []         # (x0, y0, x1, y1, what) for check_text()
        self._bb = None
        self.page = None        # (w, h), measured in render()

    # -- library -------------------------------------------------------
    def _emit_def(self, name, value, style, pins, gfx, extent,
                  hide_numbers=False, hide_names=False, power=False,
                  ref_prefix="U", name_offset=0.508, tb=(False, False)):
        """pins: list of (num, pname, px, py, angle, length, etype)."""
        head = [f'\t\t(symbol "gen:{esc(name)}"']
        if power:
            head.append("\t\t\t(power)")
        head += [f'\t\t\t(pin_numbers (hide {"yes" if hide_numbers else "no"}))',
                 f'\t\t\t(pin_names (offset {name_offset})'
                 + (' (hide yes))' if hide_names else ')'),
                 "\t\t\t(exclude_from_sim no)",
                 "\t\t\t(in_bom yes)",
                 "\t\t\t(on_board yes)",
                 f'\t\t\t(property "Reference" "{ref_prefix}" (at 0 0 0)'
                 f"\n\t\t\t\t{eff(hide=True)})",
                 f'\t\t\t(property "Value" "{esc(value)}" (at 0 0 0)'
                 f"\n\t\t\t\t{eff(hide=True)})",
                 f'\t\t\t(property "Footprint" "" (at 0 0 0)'
                 f"\n\t\t\t\t{eff(hide=True)})",
                 f'\t\t\t(symbol "{esc(name)}_0_1"']
        head += ["\t\t\t\t" + g for g in gfx]
        head.append("\t\t\t)")
        head.append(f'\t\t\t(symbol "{esc(name)}_1_1"')
        for p in pins:
            num, pname, px, py, ang, ln, etype = p[:7]
            hid = " (hide yes)" if len(p) > 7 and p[7] else ""
            head.append(f"\t\t\t\t(pin {etype} line (at {q(px)} {q(py)} {ang})"
                        f" (length {q(ln)}){hid}")
            head.append(f'\t\t\t\t\t(name "{esc(pname)}" {FONT})')
            head.append(f'\t\t\t\t\t(number "{esc(num)}" {FONT}))')
        head.append("\t\t\t)")
        head.append("\t\t)")
        anchors = {p[0]: (p[2], p[3]) for p in pins}
        self.defs[name] = SymDef(name, style, anchors, extent,
                                 "\n".join(head), tb)

    def defbox(self, name, value, sides, min_w=0.0):
        """sides: dict with 'l','r','t','b' -> list of slots, each None or
        (num, pname) or (num, pname, [more_nums]). The third form stacks
        several pads on one graphical pin — KiCad's idiom for pads that are
        internally connected (the ESD array's two IO1 pads, a crystal's two
        ground tabs), which is the only honest way to draw them as one net."""
        if name in self.defs:
            return self.defs[name]
        L = list(sides.get("l", []))
        R = list(sides.get("r", []))
        T = list(sides.get("t", []))
        B = list(sides.get("b", []))
        # Top/bottom pin names run vertically INSIDE the box and would be
        # written straight through any side-pin name whose text reaches the
        # same columns. Where they would collide, reserve as many side slots
        # as the vertical name is tall so the two never share a row.
        CW = 1.3   # per-character advance, generous on purpose

        def band(side, hw):
            names = [p[1] for p in side if p]
            if not names:
                return 0
            half = (len(side) - 1) * GRID / 2.0 + 0.8      # name columns
            lw = max([len(p[1]) for p in L if p] or [0]) * CW
            rw = max([len(p[1]) for p in R if p] or [0]) * CW
            if -hw + 0.5 + lw < -half and half < hw - 0.5 - rw:
                return 0                                   # they clear
            return min(6, math.ceil(max(map(len, names)) * 1.27 / GRID) + 1)
        nv = max(len(L), len(R), 1)
        nh = max(len(T), len(B), 0)
        h = (nv + 1) * GRID
        wname = 0.0
        lw = max([len(p[1]) for p in L if p] or [0])
        rw = max([len(p[1]) for p in R if p] or [0])
        if lw or rw:
            wname = (lw + rw) * 1.15 + 5.0
        w = max((nh + 1) * GRID, wname, min_w)
        w = math.ceil(w / GRID) * GRID
        L = [None] * band(T, w / 2.0) + L + [None] * band(B, w / 2.0)
        R = [None] * band(T, w / 2.0) + R + [None] * band(B, w / 2.0)
        nv = max(len(L), len(R), 1)
        h = (nv + 1) * GRID
        hw, hh = w / 2.0, h / 2.0
        gfx = [f"(rectangle (start {q(-hw)} {q(hh)}) (end {q(hw)} {q(-hh)})",
               "\t\t\t\t\t(stroke (width 0.254) (type default))",
               "\t\t\t\t\t(fill (type background)))"]
        pins = []

        def add(p, px, py, ang):
            pins.append((p[0], p[1], px, py, ang, PINLEN, "passive"))
            for extra in (p[2] if len(p) > 2 else []):
                pins.append((extra, p[1], px, py, ang, PINLEN, "passive",
                             True))

        for i, p in enumerate(L):
            if p:
                add(p, -hw - PINLEN, hh - GRID * (i + 1), 0)
        for i, p in enumerate(R):
            if p:
                add(p, hw + PINLEN, hh - GRID * (i + 1), 180)
        x0 = -(len(T) - 1) * GRID / 2.0 if T else 0.0
        for i, p in enumerate(T):
            if p:
                add(p, x0 + GRID * i, hh + PINLEN, 270)
        x0 = -(len(B) - 1) * GRID / 2.0 if B else 0.0
        for i, p in enumerate(B):
            if p:
                add(p, x0 + GRID * i, -hh - PINLEN, 90)
        self._emit_def(name, value, "box", pins, gfx,
                       (hw + PINLEN, hh + PINLEN),
                       tb=(any(T), any(B)))
        return self.defs[name]

    def defpassives(self):
        st = "\t\t\t\t\t(stroke (width {w}) (type default))\n" \
             "\t\t\t\t\t(fill (type none)))"

        def poly(pts, w=0):
            s = " ".join(f"(xy {q(a)} {q(b)})" for a, b in pts)
            return f"(polyline (pts {s})\n" + st.format(w=w)

        # resistor
        self._emit_def("R", "R", "passive", [
            ("1", "~", 0, 3.81, 270, 1.27, "passive"),
            ("2", "~", 0, -3.81, 90, 1.27, "passive")],
            ["(rectangle (start -1.016 -2.54) (end 1.016 2.54)\n"
             "\t\t\t\t\t(stroke (width 0.254) (type default))\n"
             "\t\t\t\t\t(fill (type none)))"],
            (2.0, 3.81), hide_numbers=True, hide_names=True, ref_prefix="R")
        # capacitor
        self._emit_def("C", "C", "passive", [
            ("1", "~", 0, 3.81, 270, 2.794, "passive"),
            ("2", "~", 0, -3.81, 90, 2.794, "passive")],
            [poly([(-2.032, 0.762), (2.032, 0.762)], 0.508),
             poly([(-2.032, -0.762), (2.032, -0.762)], 0.508)],
            (2.1, 3.81), hide_numbers=True, hide_names=True, ref_prefix="C")
        # inductor
        arcs = []
        for k in range(4):
            y0 = 2.54 - 1.27 * k
            arcs.append(f"(arc (start 0 {q(y0)}) (mid 0.6323 {q(y0 - 0.635)})"
                        f" (end 0 {q(y0 - 1.27)})\n"
                        "\t\t\t\t\t(stroke (width 0) (type default))\n"
                        "\t\t\t\t\t(fill (type none)))")
        self._emit_def("L", "L", "passive", [
            ("1", "~", 0, 3.81, 270, 1.27, "passive"),
            ("2", "~", 0, -3.81, 90, 1.27, "passive")],
            arcs, (1.5, 3.81), hide_numbers=True, hide_names=True,
            ref_prefix="L")
        # 4-pin crystal, GND on 2/4
        self._emit_def("XTAL", "Crystal", "passive", [
            ("1", "~", -3.81, 0, 0, 1.27, "passive"),
            ("3", "~", 3.81, 0, 180, 1.27, "passive"),
            ("2", "~", 0, -5.08, 90, 1.27, "passive"),
            ("4", "~", 0, -5.08, 90, 1.27, "passive", True)],
            [poly([(-2.54, 2.286), (-2.54, 3.556), (2.54, 3.556),
                   (2.54, 2.286)]),
             poly([(-2.54, -2.286), (-2.54, -3.556), (2.54, -3.556),
                   (2.54, -2.286)]),
             poly([(-2.54, 0), (-2.032, 0)]),
             poly([(2.032, 0), (2.54, 0)]),
             poly([(-2.032, -1.27), (-2.032, 1.27)], 0.508),
             poly([(2.032, -1.27), (2.032, 1.27)], 0.508),
             poly([(0, -3.81), (0, -3.556)]),
             "(rectangle (start -1.143 2.54) (end 1.143 -2.54)\n"
             "\t\t\t\t\t(stroke (width 0.3048) (type default))\n"
             "\t\t\t\t\t(fill (type none)))"],
            (3.81, 5.08), hide_numbers=True, hide_names=True, ref_prefix="Y")
        # test point
        self._emit_def("TP", "TestPoint", "point", [
            ("1", "~", 0, 0, 90, 2.54, "passive")],
            [poly([(0, 2.54), (0, 3.048)]),
             "(circle (center 0 3.556) (radius 0.762)\n"
             "\t\t\t\t\t(stroke (width 0.254) (type default))\n"
             "\t\t\t\t\t(fill (type none)))"],
            (1.2, 4.4), hide_numbers=True, hide_names=True, ref_prefix="TP")
        # battery cell
        self._emit_def("BATT", "Battery", "passive", [
            ("1", "+", 0, 3.81, 270, 2.54, "passive"),
            ("2", "-", 0, -3.81, 90, 2.54, "passive")],
            [poly([(-2.54, 1.27), (2.54, 1.27)]),
             poly([(-1.27, -1.27), (1.27, -1.27)], 0.762),
             poly([(0, 1.27), (0, 0.508)]),
             poly([(-2.54, 0.508), (2.54, 0.508)], 0.0),
             poly([(-1.27, -0.508), (1.27, -0.508)], 0.762),
             poly([(0, -1.27), (0, -1.27)])],
            (2.7, 3.81), hide_numbers=True, hide_names=True, ref_prefix="BT")
        # 4-terminal tact switch. Two terminals leave each side of the body
        # and are the same node; the LCSC footprint numbers them across the
        # part, so the blades are {1,3} (one side) and {2,4} (the other) —
        # which is why the numbering here is not 1,2 | 3,4.
        self._emit_def("SW_PUSH", "SW_Push", "passive", [
            ("1", "~", -6.35, 2.54, 0, 2.54, "passive"),
            ("3", "~", -6.35, -2.54, 0, 2.54, "passive"),
            ("2", "~", 6.35, 2.54, 180, 2.54, "passive"),
            ("4", "~", 6.35, -2.54, 180, 2.54, "passive")],
            [poly([(-3.81, 2.54), (-2.54, 2.54), (-2.54, -2.54),
                   (-3.81, -2.54)]),
             poly([(3.81, 2.54), (2.54, 2.54), (2.54, -2.54), (3.81, -2.54)]),
             poly([(-3.302, 1.27), (3.302, 1.27)]),
             poly([(0, 1.27), (0, 3.302)]),
             poly([(-1.905, 3.302), (1.905, 3.302)])],
            (6.35, 4.4), hide_numbers=True, hide_names=True, ref_prefix="SW")
        # dual series Schottky (BAT54SW): 1 = A1, 2 = K2, 3 = K1+A2 mid tap.
        # Conduction left-to-right pin1 -> pin3 -> pin2; the tap hangs down.
        self._emit_def("D_SS", "D_SS", "passive", [
            ("1", "A1", -7.62, 0, 0, 3.81, "passive"),
            ("2", "K2", 7.62, 0, 180, 3.81, "passive"),
            ("3", "K1A2", 0, -5.08, 90, 3.81, "passive")],
            [poly([(-3.81, 1.27), (-3.81, -1.27), (-1.27, 0), (-3.81, 1.27)]),
             poly([(-0.762, 1.016), (-1.27, 1.016), (-1.27, -1.016),
                   (-1.778, -1.016)], 0.254),
             poly([(-1.27, 0), (1.27, 0)]),
             poly([(1.27, 1.27), (1.27, -1.27), (3.81, 0), (1.27, 1.27)]),
             poly([(4.318, 1.016), (3.81, 1.016), (3.81, -1.016),
                   (3.302, -1.016)], 0.254),
             poly([(0, 0), (0, -1.27)]),
             "(circle (center 0 0) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))"],
            (7.62, 5.08), hide_numbers=True, hide_names=True, ref_prefix="D")
        # single Schottky (D3, VBUS -> VSYS): 1 = K, 2 = A, conduction
        # left-to-right. Same bar-with-hooks as one half of D_SS.
        self._emit_def("D_SCH", "D_SCH", "passive", [
            ("2", "A", -6.35, 0, 0, 3.81, "passive"),
            ("1", "K", 6.35, 0, 180, 3.81, "passive")],
            [poly([(-2.54, 1.27), (-2.54, -1.27), (0, 0), (-2.54, 1.27)]),
             poly([(0.508, 1.016), (0, 1.016), (0, -1.016), (-0.508, -1.016)],
                  0.254),
             poly([(0, 0), (2.54, 0)])],
            (6.35, 2.54), hide_numbers=True, hide_names=True, ref_prefix="D")

        # enhancement MOSFETs, 1 = G (left), 2 = S (bottom), 3 = D (top) —
        # the SOT-323/SOT-23 3-lead pad order, so the symbol pin numbers are
        # the footprint pad numbers with no translation table.
        def fet(name, p_channel):
            arrow = ([(-0.508, 0.635), (-0.508, -0.635), (0.508, 0),
                      (-0.508, 0.635)] if p_channel else
                     [(0.508, 0.635), (0.508, -0.635), (-0.508, 0),
                      (0.508, 0.635)])
            self._emit_def(name, name, "passive", [
                ("1", "G", -7.62, 0, 0, 3.81, "passive"),
                ("2", "S", 2.54, -7.62, 90, 3.81, "passive"),
                ("3", "D", 2.54, 7.62, 270, 3.81, "passive")],
                [poly([(-3.81, 0), (-2.54, 0)]),
                 poly([(-2.54, 2.54), (-2.54, -2.54)]),
                 poly([(-1.27, 2.54), (-1.27, 1.27)]),
                 poly([(-1.27, 0.635), (-1.27, -0.635)]),
                 poly([(-1.27, -1.27), (-1.27, -2.54)]),
                 poly([(-1.27, 1.905), (2.54, 1.905), (2.54, 3.81)]),
                 poly([(-1.27, -1.905), (2.54, -1.905), (2.54, -3.81)]),
                 poly([(-1.27, 0), (2.54, 0)]),
                 poly([(2.54, 0), (2.54, -1.905)]),
                 poly(arrow)],
                (7.62, 7.62), hide_numbers=True, hide_names=True,
                ref_prefix="Q")

        fet("Q_PMOS", True)
        fet("Q_NMOS", False)
        # SPDT slide switch, 2 = common
        self._emit_def("SW_SPDT", "SW_SPDT", "passive", [
            ("1", "~", -6.35, 2.54, 0, 3.81, "passive"),
            ("3", "~", -6.35, -2.54, 0, 3.81, "passive"),
            ("2", "~", 6.35, 0, 180, 3.81, "passive")],
            ["(circle (center -2.286 2.54) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))",
             "(circle (center -2.286 -2.54) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))",
             "(circle (center 2.286 0) (radius 0.254)\n"
             "\t\t\t\t\t(stroke (width 0) (type default))\n"
             "\t\t\t\t\t(fill (type outline)))",
             poly([(2.286, 0), (-2.032, 2.032)])],
            (6.35, 4.4), hide_numbers=True, hide_names=True, ref_prefix="SW")

    def defpower(self, rail):
        name = f"P_{rail}"
        if name in self.defs:
            return self.defs[name]
        st = "\t\t\t\t\t(stroke (width 0) (type default))\n" \
             "\t\t\t\t\t(fill (type none)))"

        def poly(pts):
            s = " ".join(f"(xy {q(a)} {q(b)})" for a, b in pts)
            return f"(polyline (pts {s})\n" + st
        if rail == "GND":
            gfx = [poly([(0, 0), (0, -1.27)]),
                   poly([(-1.27, -1.27), (1.27, -1.27), (0, -2.54),
                         (-1.27, -1.27)])]
            ext = (1.5, 4.6)
        else:
            gfx = [poly([(0, 0), (0, 2.54)]),
                   poly([(-0.762, 1.27), (0, 2.54), (0.762, 1.27)])]
            ext = (1.5, 4.6)
        self._emit_def(name, rail, "power",
                       [("1", rail, 0, 0, 90 if rail != "GND" else 270, 0,
                         "power_in")],
                       gfx, ext, hide_numbers=True, hide_names=True,
                       power=True, ref_prefix="#PWR")
        return self.defs[name]

    # -- bbox / frames -------------------------------------------------
    def _grow(self, x, y, pad=0.0):
        """Grow the current block's frame box.

        Only symbols, labels and notes count — NOT the wires. A block's
        frame is meant to say "these parts belong together"; the wires that
        leave it to reach the MCU would otherwise stretch every satellite
        frame back over the chip it connects to.
        """
        if self._bb is None:
            self._bb = [x - pad, y - pad, x + pad, y + pad]
        else:
            b = self._bb
            b[0] = min(b[0], x - pad)
            b[1] = min(b[1], y - pad)
            b[2] = max(b[2], x + pad)
            b[3] = max(b[3], y + pad)

    def begin(self, title):
        self._title = title
        self._bb = None

    def end(self, pad=5.0):
        b = self._bb
        assert b, f"empty block {self._title}"
        x0, y0, x1, y1 = b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        s = " ".join(f"(xy {q(a)} {q(c)})" for a, c in pts)
        self.body.append(
            f"\t(polyline (pts {s})\n"
            "\t\t(stroke (width 0.1524) (type dash))\n"
            f'\t\t(uuid "{uid("frame", self._title)}"))')
        self.body.append(
            f'\t(text "{esc(self._title)}" (at {q(x0 + 1.27)} {q(y0 - 1.6)} 0)'
            f"\n\t\t{eff(2.2, bold=True, just='left bottom')}"
            f'\n\t\t(uuid "{uid("ftitle", self._title)}"))')
        self.frames.append((x0, y0 - 6.0, x1, y1, self._title))
        self._bb = None

    # -- text collisions -----------------------------------------------
    # Every readability bug this sheet has ever had was a label sitting on
    # a wire or on another label. Nothing in KiCad complains about that, so
    # the generator has to: record a box for every piece of text drawn and
    # refuse to emit a sheet where one lands on a wire or on its neighbour.
    def _text_box(self, s, x, y, size, just):
        w = len(str(s)) * size * 0.72
        j = (just or "").split()
        if "right" in j:
            x0, x1 = x - w, x
        elif "left" in j:
            x0, x1 = x, x + w
        else:
            x0, x1 = x - w / 2.0, x + w / 2.0
        # KiCad anchors vertically by baseline-ish; which side the glyphs
        # fall on depends on the justify token, so claim both. Conservative
        # in the safe direction: a false positive costs a nudge, a missed
        # one ships an unreadable sheet.
        return (x0, y - size, x1, y + size)

    def _note_text(self, s, x, y, size, just, what, on_wire=False,
                   group=None):
        """on_wire: a net label is SUPPOSED to sit on the wire it names, so
        those are only checked against other text, never against copper.
        group: consecutive lines of one wrapped note share a group and are
        allowed to sit tight against each other."""
        if not str(s).strip():
            return
        self.texts.append(self._text_box(s, x, y, size, just)
                          + (what, on_wire, group))

    @staticmethod
    def _overlap(a, b, pad=0.0):
        return (a[0] < b[2] - pad and b[0] < a[2] - pad
                and a[1] < b[3] - pad and b[1] < a[3] - pad)

    def check_text(self, verbose=False):
        """Report text that lands on a wire or on other text."""
        bad = []
        for i, t in enumerate(self.texts):
            for u in self.texts[i + 1:]:
                if t[6] is not None and t[6] == u[6]:
                    continue           # two lines of the same note
                if self._overlap(t, u, pad=0.01):
                    bad.append(f"{t[4]!r} overlaps text {u[4]!r}")
        for t in self.texts:
            if t[5]:
                continue
            for a, b in self.wires:
                if a[1] == b[1]:                       # horizontal run
                    x0, x1 = sorted((a[0], b[0]))
                    seg = (x0, a[1], x1, a[1])
                else:
                    y0, y1 = sorted((a[1], b[1]))
                    seg = (a[0], y0, a[0], y1)
                # text needs air around it, not just non-overlap
                if (t[0] - 0.5 < seg[2] and seg[0] < t[2] + 0.5
                        and t[1] - 0.5 < seg[3] and seg[1] < t[3] + 0.5):
                    bad.append(f"{t[4]!r} sits on the wire {a}-{b}")
                    break
        if verbose:
            for m in sorted(set(bad)):
                print("  TEXT:", m)
        return sorted(set(bad))

    def measure_page(self):
        """Paper size = everything drawn, plus a margin, on a 5mm grid."""
        x1 = max(f[2] for f in self.frames)
        y1 = max(f[3] for f in self.frames)
        for s, x, y, size in self.head:
            x1 = max(x1, x + len(s) * size * 0.72)
            y1 = max(y1, y)
        w = math.ceil((x1 + MARGIN) / 5.0) * 5.0
        h = math.ceil((y1 + MARGIN) / 5.0) * 5.0
        # nothing may sit under the title block in the bottom-right corner
        tb = (w - MARGIN - TITLE_BLOCK[0], h - MARGIN - TITLE_BLOCK[1])
        clash = [f[4] for f in self.frames if f[2] > tb[0] and f[3] > tb[1]]
        if clash:
            h = math.ceil((y1 + MARGIN + TITLE_BLOCK[1]) / 5.0) * 5.0
        self.page = (w, h)
        return self.page

    def check_frames(self, verbose=False):
        """Blocks must not overlap and must fit the sheet.

        Set SCH_LAYOUT=1 to print every block's measured box first — that
        listing is how the anchors below were chosen, and it is what you
        want when a netlist change makes a block outgrow its slot.
        """
        if verbose:
            for f in sorted(self.frames, key=lambda f: (f[0], f[1])):
                print(f"  [{f[0]:7.1f} {f[1]:7.1f}] .. [{f[2]:7.1f} "
                      f"{f[3]:7.1f}]  {f[2]-f[0]:6.1f} x {f[3]-f[1]:6.1f}"
                      f"  {f[4]}")
        bad = []
        for i in range(len(self.frames)):
            for j in range(i + 1, len(self.frames)):
                a, b = self.frames[i], self.frames[j]
                if (a[0] < b[2] and b[0] < a[2]
                        and a[1] < b[3] and b[1] < a[3]):
                    bad.append(f"{a[4]!r} overlaps {b[4]!r}")
        assert not bad, "block frames overlap:\n  " + "\n  ".join(bad)
        for f in self.frames:
            assert f[0] > 0 and f[1] > 0, \
                f"block {f[4]!r} runs off the top/left of the sheet: {f[:4]}"

    # -- placement -----------------------------------------------------
    def place(self, symname, ref, value, x, y, rot=0, footprint="",
              hide_value=False, ref_off=None):
        d = self.defs[symname]
        assert ref not in self.refs, f"duplicate reference {ref}"
        self.refs.add(ref)
        x, y = q(x), q(y)
        hw, hh = d.extent
        if rot in (90, 270):
            hw, hh = hh, hw
        self._grow(x - hw, y - hh)
        self._grow(x + hw, y + hh)
        # reference / value text placement
        if d.style == "box":
            rx = x - hw
            ry = y - hh - (4.6 if d.has_top else 1.6)
            rj = "left bottom"
            # The value goes under the box, but bottom pins drop their wires
            # from the middle of that edge straight into a ground symbol, so
            # run the value leftwards out of the centre instead of starting
            # at the left edge and crossing it.
            vx = x - 3.81 if d.has_bot else x - hw
            vy = y + hh + (4.4 if d.has_bot else 3.4)
            vj = "right bottom" if d.has_bot else "left bottom"
        elif d.style == "point":
            # A test point is a stub: the pad faces its wire and the body
            # (the circle) faces away, so the only free side is behind it.
            rx, ry, rj = x - hw - 0.6, y - 2.0, "right bottom"
            vx, vy, vj = x - hw - 0.6, y + 1.1, "right bottom"
        elif d.style == "power":
            rx, ry, rj = x, y, "left bottom"
            vx, vj = x, "center"
            vy = y + 4.6 if symname.endswith("GND") else y - 3.4
            if rot == 180:
                vy = y - 4.0 if symname.endswith("GND") else y + 5.2
        else:
            # Put the text where this part's pins are NOT. Every pin grows a
            # wire, so the free side depends on which way the part is turned,
            # not on the rotation angle as such: read it off the placed pin
            # offsets and pick the axis with the shorter reach.
            pts = [xf(px, py, rot) for px, py in d.pins.values()]
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            if max(ys) - min(ys) >= max(xs) - min(xs):
                # pins stack vertically -> park the text alongside the body,
                # between the two pins so it cannot reach either run
                rx, ry, rj = x + hw + 0.6, y - 2.0, "left bottom"
                vx, vy, vj = x + hw + 0.6, y + 1.1, "left bottom"
            else:
                # pins run left-right -> stack the text above and below,
                # stepped off the pin axis so it clears the wires' corners
                rx, ry, rj = x + 1.9, y - hh - 2.8, "left bottom"
                vx, vy, vj = x + 1.9, y + hh + 4.2, "left bottom"
        if ref_off:
            rx, ry = x + ref_off[0], y + ref_off[1]
            vx, vy = x + ref_off[0], y + ref_off[1] + 3.4
        self._grow(rx, ry - 1.3)
        self._grow(rx + len(ref) * 1.0, ry)
        if d.style != "power":
            self._note_text(ref, rx, ry, 1.27, rj, f"{ref} ref")
        if not hide_value:
            self._note_text(value, vx, vy, 1.27, vj, f"{ref} value {value!r}")
        # KiCad adds the symbol's orientation to a property's own angle, and
        # renders a resulting 180 deg upside-down. Cancel the rotation for
        # quarter turns; a half turn already reads the right way up.
        tang = 0 if rot in (0, 180) else (360 - rot) % 360
        parts = [f'\t(symbol (lib_id "gen:{esc(symname)}")',
                 f"\t\t(at {x} {y} {rot})",
                 "\t\t(unit 1) (exclude_from_sim no) (in_bom yes)"
                 " (on_board yes) (dnp no)",
                 f'\t\t(uuid "{uid("sym", ref)}")',
                 f'\t\t(property "Reference" "{esc(ref)}" '
                 f"(at {q(rx)} {q(ry)} {tang})\n\t\t\t"
                 + eff(1.27, just=rj, hide=(d.style == "power")) + ")",
                 f'\t\t(property "Value" "{esc(value)}" '
                 f"(at {q(vx)} {q(vy)} {tang})\n\t\t\t"
                 + eff(1.27, just=vj, hide=hide_value) + ")"]
        if footprint:
            parts.append(f'\t\t(property "Footprint" "{FP_LIB}:{esc(footprint)}"'
                         f" (at {x} {y} 0)\n\t\t\t{eff(hide=True)})")
        for num in d.pins:
            parts.append(f'\t\t(pin "{esc(num)}" (uuid "{uid("pin", ref, num)}"))')
        parts.append('\t\t(instances (project "earring"'
                     f'\n\t\t\t(path "/{SHEET_UUID}"'
                     f'\n\t\t\t\t(reference "{esc(ref)}") (unit 1)))))')
        self.body.append("\n".join(parts))
        out = {}
        for num, (px, py) in d.pins.items():
            dx, dy = xf(px, py, rot)
            out[num] = (q(x + dx), q(y + dy))
        return out

    # -- connectivity items --------------------------------------------
    def wire(self, a, b):
        a, b = (q(a[0]), q(a[1])), (q(b[0]), q(b[1]))
        if a == b:
            return
        assert a[0] == b[0] or a[1] == b[1], \
            f"diagonal wire {a} -> {b} (schematic wires must be orthogonal)"
        self.wires.append((a, b))

    def path(self, *pts):
        for a, b in zip(pts, pts[1:]):
            self.wire(a, b)

    def junction(self, p):
        self.jpts.add((q(p[0]), q(p[1])))

    def nc(self, p):
        self.body.append(
            f"\t(no_connect (at {q(p[0])} {q(p[1])})"
            f'\n\t\t(uuid "{uid("nc", p)}"))')

    def label(self, net, p, rot=0, just="left", size=1.0):
        """Name a wire that KiCad would otherwise auto-name.

        These are GLOBAL labels even though the run is local, because a
        plain label on the root sheet comes back out of the netlister as
        `/LED_D7`, and the board is matched to circuit.py by net name — a
        rename would relabel every net on a hand-routed board. Drawn small,
        so naming a wire costs a word rather than a box.
        """
        self.glabel(net, p, rot=rot, just=just, size=size)

    def glabel(self, net, p, rot=0, just="left", size=1.27):
        # the label box is the text plus KiCad's arrow shape around it
        if rot == 0:
            self._note_text(f" {net} ", p[0], p[1], size, "left",
                            f"label {net}", on_wire=True)
        elif rot == 180:
            self._note_text(f" {net} ", p[0], p[1], size, "right",
                            f"label {net}", on_wire=True)
        self.body.append(
            f'\t(global_label "{esc(net)}" (shape input) '
            f"(at {q(p[0])} {q(p[1])} {rot})\n\t\t"
            + eff(size, just=just) + f'\n\t\t(uuid "{uid("gl", net, p)}"))')

    def note(self, s, x, y, width, size=1.4):
        """Block note, wrapped to `width` mm. KiCad has no text box, and an
        unwrapped note stretches the block frame across half the sheet."""
        cols = max(16, int(width / (size * 0.72)))
        line, lines = "", []
        for word in s.split():
            if line and len(line) + 1 + len(word) > cols:
                lines.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        if line:
            lines.append(line)
        for i, ln in enumerate(lines):
            self.text(ln, x, y + i * size * 1.9, size=size,
                      group=("note", q(x), q(y)))

    def text(self, s, x, y, size=1.27, bold=False, just="left bottom",
             frame=True, group=None):
        if not frame:
            self.head.append((s, x, y, size))
        if frame:
            self._grow(x, y - size)
            self._grow(x + len(s) * size * 0.72, y)
            self._note_text(s, x, y, size, just, f"note {s[:24]!r}",
                            group=group)
        self.body.append(
            f'\t(text "{esc(s)}" (at {q(x)} {q(y)} 0)\n\t\t'
            + eff(size, bold=bold, just=just)
            + f'\n\t\t(uuid "{uid("txt", x, y, s[:28])}"))')

    # -- convenience ---------------------------------------------------
    def rail(self, net, p, rot=0):
        """Power/ground symbol whose pin lands exactly on p."""
        self.defpower(net)
        self.pwr_n += 1
        self.place(f"P_{net}", f"#PWR{self.pwr_n:04d}", net, p[0], p[1],
                   rot=rot)
        return p

    @staticmethod
    def _interior(a, b, p):
        """Is p strictly between the ends of the orthogonal segment a-b?"""
        if a[0] == b[0] == p[0]:
            return min(a[1], b[1]) < p[1] < max(a[1], b[1])
        if a[1] == b[1] == p[1]:
            return min(a[0], b[0]) < p[0] < max(a[0], b[0])
        return False

    def finish_wires(self):
        """Split every wire at the junctions on it, and put a junction
        wherever one wire ENDS in the middle of another.

        Both steps are what the KiCad editor does as you draw. Without
        them the connectivity engine only breaks a run at its first
        junction, so a single long rail wire silently connects the first
        two taps and leaves the rest floating — which is exactly what the
        netlist round-trip caught the first time this sheet was drawn.
        """
        ends = set()
        for a, b in self.wires:
            ends.add(a)
            ends.add(b)
        stray = set()
        for a, b in self.wires:
            for e in ends:
                if self._interior(a, b, e):
                    if e not in self.jpts:
                        stray.add(e)
                    self.jpts.add(e)
        # Every intended tap is declared with junction(); anything else that
        # lands mid-wire is a layout collision that would silently short two
        # nets, so refuse to emit it.
        assert not stray, ("wires meet at undeclared points (layout "
                           "collision): "
                           + ", ".join(f"({x}, {y})" for x, y in sorted(stray)))
        # Crossings. Two wires that cross without a junction are legal but
        # they are exactly where a net label lands on two nets at once (a
        # label attaches to every wire under it), and they are the thing
        # that makes a sheet hard to read. Route around them instead.
        hs = [(a, b) for a, b in self.wires if a[1] == b[1]]
        vs = [(a, b) for a, b in self.wires if a[0] == b[0] and a[1] != b[1]]
        cross = []
        for ha, hb in hs:
            x0, x1 = sorted((ha[0], hb[0]))
            for va, vb in vs:
                y0, y1 = sorted((va[1], vb[1]))
                if x0 < va[0] < x1 and y0 < ha[1] < y1:
                    cross.append((va[0], ha[1]))
        assert not cross, ("wires cross without connecting: "
                           + ", ".join(f"({x}, {y})" for x, y in sorted(set(cross))))
        out = []
        for a, b in self.wires:
            cuts = sorted((p for p in self.jpts if self._interior(a, b, p)),
                          key=lambda p: (p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2)
            prev = a
            for c in cuts:
                out.append((prev, c))
                prev = c
            out.append((prev, b))
        seen = set()
        for a, b in out:
            k = tuple(sorted([a, b]))
            if k in seen:
                continue
            seen.add(k)
            self.body.append(
                f"\t(wire (pts (xy {a[0]} {a[1]}) (xy {b[0]} {b[1]}))"
                "\n\t\t(stroke (width 0) (type default))"
                f'\n\t\t(uuid "{uid("w", a, b)}"))')
        for p in sorted(self.jpts):
            self.body.append(
                f"\t(junction (at {p[0]} {p[1]}) (diameter 0)"
                " (color 0 0 0 0)"
                f'\n\t\t(uuid "{uid("j", p)}"))')

    def render(self):
        self.finish_wires()
        w, h = self.page or self.measure_page()
        return ("(kicad_sch\n\t(version 20250114)\n"
                '\t(generator "gen_schematic")\n'
                '\t(generator_version "9.0")\n'
                f'\t(uuid "{SHEET_UUID}")\n'
                f'\t(paper "User" {w} {h})\n'
                "\t(lib_symbols\n"
                + "\n".join(d.sexpr for d in self.defs.values())
                + "\n\t)\n" + "\n".join(self.body) + "\n)\n")


# ---------------------------------------------------------------------------
# IC symbol pin maps: pins are placed by function, not by pad order.
# 'l'/'r'/'t'/'b' = box side, None = blank slot (used to line pins up with
# whatever they wire to, and to keep side pins clear of the vertical pin
# names on the top/bottom edges).
# ---------------------------------------------------------------------------
def mcu_sides():
    gp = {g: p for g, p in GPIO.items()}
    used = {29: "GPIO18", 3: "GPIO1", 9: "GPIO6", 15: "GPIO11", 12: "GPIO8",
            31: "GPIO19", 42: "GPIO28", 40: "GPIO26/ADC0",
            43: "GPIO29/ADC3"}
    unused = [(gp[g], f"GPIO{g}") for g in sorted(gp)
              if gp[g] not in used and gp[g] != 43]
    # Side pins are grouped by the block they wire to, with the gaps sized so
    # each satellite block gets its own band of sheet next to the chip. The
    # 22 unused GPIOs go along the bottom edge, where a row of no-connect
    # crosses costs width the box already has instead of 56mm of side edge
    # that the flash, crystal and SWD clusters need.
    left = ([(26, "RUN"), (24, "SWCLK"), (25, "SWDIO")]
            + [None] * 14
            + [(60, "QSPI_SS"), (56, "QSPI_SCLK"), (57, "QSPI_SD0"),
               (59, "QSPI_SD1"), (58, "QSPI_SD2"), (55, "QSPI_SD3")]
            + [None] * 17
            + [(21, "XIN"), (22, "XOUT")]
            + [None] * 8
            + [(51, "USB_DM"), (52, "USB_DP")])
    right = [(29, "GPIO18"), (3, "GPIO1"), (9, "GPIO6"), (15, "GPIO11"),
             (12, "GPIO8"), (31, "GPIO19"), (42, "GPIO28"),
             (40, "GPIO26/ADC0"), (43, "GPIO29/ADC3")]
    top = [(1, "IOVDD"), (11, "IOVDD"), (20, "IOVDD"), (30, "IOVDD"),
           (38, "IOVDD"), (45, "IOVDD"), (54, "QSPI_IOVDD"),
           (53, "USB_OTP_VDD"), (44, "ADC_AVDD"), None,
           (6, "DVDD"), (23, "DVDD"), (39, "DVDD")]
    bot = ([(61, "GND(EP)"), (47, "VREG_PGND"), (48, "VREG_LX"),
            (50, "VREG_FB"), (46, "VREG_AVDD"), (49, "VREG_VIN")]
           + [None] * 2 + unused)
    return {"l": [(str(a), b) if a else None for a, b in
                  [(p or (None, None)) for p in left]],
            "r": [(str(a), b) if a else None for a, b in
                  [(p or (None, None)) for p in right]],
            "t": [(str(a), b) if a else None for a, b in
                  [(p or (None, None)) for p in top]],
            "b": [(str(a), b) if a else None for a, b in
                  [(p or (None, None)) for p in bot]]}


IC_SIDES = {
    "flash": {"l": [("8", "VCC"), None, None, ("4", "GND"), ("9", "GND(EP)")],
              "r": [("1", "/CS"), ("6", "CLK"), ("5", "DI/IO0"),
                    ("2", "DO/IO1"), ("3", "/WP/IO2"), ("7", "/HOLD/IO3")]},
    "charger": {"l": [("4", "VCC"), ("8", "CE"), ("2", "PROG"), ("1", "TEMP")],
                "r": [("5", "BAT"), None, None, ("6", "DONE"), ("7", "CHRG")],
                "b": [("3", "GND"), ("9", "GND(EP)")]},
    "ldo": {"l": [("6", "IN"), None, ("4", "EN")],
            "r": [("1", "OUT"), None, ("5", "NC"), ("2", "NC")],
            "b": [("3", "GND"), ("EP", "EP")]},
    "load_switch": {"l": [("A2", "VIN"), None, ("B2", "ON")],
                    "r": [("A1", "VOUT")],
                    "b": [("B1", "GND")]},
    # The array's two IO1 pads (1, 6) and two IO2 pads (3, 4) are the same
    # node inside the part, so they are stacked on one graphical pin and the
    # symbol reads as what it is: a shunt sitting between D+ and D-.
    "usb_esd": {"t": [("1", "IO1", ["6"])], "b": [("3", "IO2", ["4"])],
                "l": [("5", "VBUS")], "r": [("2", "GND")]},
    "usb_conn": {"r": [("A4B9", "VBUS"), ("B4A9", "VBUS"), None,
                       ("A6", "D+"), ("B6", "D+")] + [None] * 10
                 + [("A7", "D-"), ("B7", "D-"), None,
                    ("A5", "CC1"), ("B5", "CC2"), None,
                    ("A8", "SBU1"), ("B8", "SBU2")] + [None] * 3,
                 "b": [("A1B12", "GND"), ("B1A12", "GND"), ("1", "SHLD"),
                       ("2", "SHLD"), ("3", "SHLD"), ("4", "SHLD")]},
    # Serial trio is 12=CS / 13=SCL / 14=SDA (ST ds Table 2) — the bus pair
    # faces the MCU on the left, the mode strap joins SDx/SCx on the right.
    "imu": {"l": [("14", "SDA"), ("13", "SCL"), None, ("4", "INT1"),
                  ("9", "INT2"), ("10", "NC"), ("11", "NC")],
            "r": [("12", "CS"), ("2", "SDx"), ("3", "SCx"), None,
                  ("1", "SDO/SA0")],
            "t": [("8", "VDD"), ("5", "VDDIO")],
            "b": [("6", "GND"), ("7", "GND")]},
    "led": {"l": [None, ("2", "DI"), None],
            "r": [None, ("4", "DO"), None],
            "t": [("3", "VDD")], "b": [("1", "GND")]},
    # ALS-PT19 phototransistor: collector up to 3V3, emitter down into
    # the LIGHT node (load R + filter C hang off it)
    "light_sensor": {"t": [("1", "C")], "b": [("2", "E")]},
}

# a little extra width where the automatic sizing leaves names touching
IC_MIN_W = {"led": 12.7}

PASSIVE_SYM = {"r_": "R", "c_": "C", "vreg_inductor": "L", "crystal": "XTAL",
               "testpoint": "TP", "battery_clip": "BATT",
               "bootsel_button": "SW_PUSH", "slide_switch": "SW_SPDT",
               "or_diode": "D_SS", "sys_diode": "D_SCH",
               "oring_pfet": "Q_PMOS", "lvl_nfet": "Q_NMOS"}


def sym_for(part):
    for k, v in PASSIVE_SYM.items():
        if part == k or part.startswith(k):
            return v
    return part


# ---------------------------------------------------------------------------
# electrical bookkeeping: every pin drawn must match circuit.py, and every
# pin in circuit.py must be drawn.
# ---------------------------------------------------------------------------
class Book:
    def __init__(self, comps):
        self.comps = comps
        self.seen = set()

    def net(self, ref, pin):
        return self.comps[ref].pins[str(pin)]

    def take(self, ref, pin, expect=None):
        p = str(pin)
        assert p in self.comps[ref].pins, f"{ref} has no pin {p}"
        got = self.comps[ref].pins[p]
        if expect is not None:
            assert got == expect, f"{ref}.{p} is net {got!r}, expected {expect!r}"
        self.seen.add((ref, p))
        return got

    def report(self):
        missing = []
        for ref, c in self.comps.items():
            for p in c.pins:
                if (ref, p) not in self.seen:
                    missing.append(f"{ref}.{p}")
        assert not missing, ("pins drawn but not connected to anything: "
                             + ", ".join(missing[:40]))


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------
def put(s, cir, ref, x, y, rot=0, hide_value=False, ref_off=None):
    c = cir.components[ref]
    name = sym_for(c.part)
    return s.place(name, ref, c.value, x, y, rot=rot,
                   footprint=c.footprint, hide_value=hide_value,
                   ref_off=ref_off)


def vdrop(s, cir, bk, ref, x, ytop, rail="GND", drop=3.81):
    """2-pin part hanging down from (x, ytop) into a rail symbol below."""
    p = put(s, cir, ref, x, ytop + 3.81)
    bk.take(ref, "1")
    bk.take(ref, "2", rail)
    s.wire(p["2"], (x, p["2"][1] + drop))
    s.rail(rail, (x, p["2"][1] + drop))
    return p


def blk_usb(s, cir, bk, x, y):
    s.begin("USB-C receptacle / ESD / series R")
    j = put(s, cir, "J1", x, y, hide_value=True)
    xr = j["A4B9"][0]
    for n in ("A4B9", "B4A9"):
        bk.take("J1", n, "VBUS")
    xv = xr + 12.7
    s.wire(j["A4B9"], (xv, j["A4B9"][1]))
    s.wire(j["B4A9"], (xv, j["B4A9"][1]))
    s.wire((xv, j["A4B9"][1]), (xv, j["B4A9"][1]))
    ytop = j["A4B9"][1] - 15.24
    s.wire((xv, j["A4B9"][1]), (xv, ytop))
    s.junction((xv, j["A4B9"][1]))
    s.junction((xv, ytop))
    s.rail("VBUS", (xv, ytop))
    # ST USBLC6-2 ds §3: a 100n right at the array keeps VBUS stiff during
    # a positive surge, which is what the rail-to-rail clamp references.
    s.wire((xv, ytop), (xv + 12.7, ytop))
    vdrop(s, cir, bk, "C28", xv + 12.7, ytop, "GND")

    # D+ / D- pairs join, run straight out through the series resistors, and
    # the ESD array shunts both of them from between the two runs
    xd = xr + 6.35
    ydp = q((j["A6"][1] + j["B6"][1]) / 2.0)
    ydn = q((j["A7"][1] + j["B7"][1]) / 2.0)
    u5 = put(s, cir, "U5", xr + 33.02, q((ydp + ydn) / 2.0))
    assert ydp < u5["1"][1] and u5["3"][1] < ydn, \
        "the ESD array must sit between the D+ and D- runs"
    for a, b, pin, net, mid_y, rref, out in (
            ("A6", "B6", "1", "USB_C_DP", ydp, "R6", "USB_DP"),
            ("A7", "B7", "3", "USB_C_DN", ydn, "R7", "USB_DM")):
        bk.take("J1", a, net)
        bk.take("J1", b, net)
        bk.take("U5", pin, net)
        bk.take("U5", {"1": "6", "3": "4"}[pin], net)   # stacked pad
        s.wire(j[a], (xd, j[a][1]))
        s.wire(j[b], (xd, j[b][1]))
        s.wire((xd, j[a][1]), (xd, j[b][1]))
        s.junction((xd, mid_y))
        r = put(s, cir, rref, xr + 48.26, mid_y, rot=90)
        bk.take(rref, "1", net)
        bk.take(rref, "2", out)
        s.wire((xd, mid_y), r["1"])
        s.junction((u5[pin][0], mid_y))
        s.wire(u5[pin], (u5[pin][0], mid_y))
        s.label(net, (xd + 2.54, mid_y), size=1.0)
        s.wire(r["2"], (r["2"][0] + 5.08, r["2"][1]))
        s.glabel(out, (r["2"][0] + 5.08, r["2"][1]))
    bk.take("U5", "5", "VBUS")
    s.wire(u5["5"], (u5["5"][0] - 6.35, u5["5"][1]))
    s.rail("VBUS", (u5["5"][0] - 6.35, u5["5"][1]))
    bk.take("U5", "2", "GND")
    s.wire(u5["2"], (u5["2"][0] + 6.35, u5["2"][1]))
    s.rail("GND", (u5["2"][0] + 6.35, u5["2"][1]))

    # CC pulldowns: the lower pin turns down first so the two never cross
    for cc, rref, dx in (("B5", "R5", 15.24), ("A5", "R4", 27.94)):
        net = bk.take("J1", cc)
        s.wire(j[cc], (xr + dx, j[cc][1]))
        s.label(net, (xr + 7.62, j[cc][1]), size=1.0)
        s.wire((xr + dx, j[cc][1]), (xr + dx, j["B5"][1] + 6.35))
        r = put(s, cir, rref, xr + dx, j["B5"][1] + 6.35 + 3.81)
        bk.take(rref, "1", net)
        bk.take(rref, "2", "GND")
        s.wire(r["2"], (r["2"][0], r["2"][1] + 3.81))
        s.rail("GND", (r["2"][0], r["2"][1] + 3.81))
    for n in ("A8", "B8"):
        bk.take("J1", n, "")
        s.nc(j[n])

    # shield + GND legs down to a common bus
    gnds = ["A1B12", "B1A12", "1", "2", "3", "4"]
    ybus = j["A1B12"][1] + 6.35
    for n in gnds:
        bk.take("J1", n, "GND")
        s.wire(j[n], (j[n][0], ybus))
    s.wire((j[gnds[0]][0], ybus), (j[gnds[-1]][0], ybus))
    for n in gnds[1:-1]:
        s.junction((j[n][0], ybus))
    xg = j[gnds[2]][0]
    s.wire((xg, ybus), (xg, ybus + 2.54))
    s.junction((xg, ybus))
    s.rail("GND", (xg, ybus + 2.54))
    s.note("J1 is a TYPE-C-31-M-12 right-angle receptacle. VBUS is "
           "charge-only: there is no VBUS->3V3 path, the MCU always runs "
           "from the cell.", x - 8.89, ybus + 12.7, 88.0)
    s.end()


def blk_charger(s, cir, bk, x, y):
    s.begin("Li-ion charger (LGS4056H, ~41mA) + RJD2032C1 cell")
    u = put(s, cir, "U2", x, y)
    # VBUS in
    xb = u["4"][0] - 12.7
    for p in ("4", "8"):
        bk.take("U2", p, "VBUS")
        s.wire(u[p], (xb, u[p][1]))
    s.wire((xb, u["4"][1]), (xb, u["8"][1]))
    s.wire((xb, u["4"][1]), (xb, u["4"][1] - 10.16))
    s.junction((xb, u["4"][1]))
    s.rail("VBUS", (xb, u["4"][1] - 10.16))
    # VBUS bulk cap
    yc = u["4"][1] - 5.08
    s.wire((xb, yc), (xb - 12.7, yc))
    s.junction((xb, yc))
    vdrop(s, cir, bk, "C16", xb - 12.7, yc, "GND")
    # PROG resistor
    bk.take("U2", "2", "PROG")
    xp = u["2"][0] - 20.32
    s.wire(u["2"], (xp, u["2"][1]))
    s.label("PROG", (xp + 3.81, u["2"][1]), size=1.0)
    s.wire((xp, u["2"][1]), (xp, u["2"][1] + 5.08))
    vdrop(s, cir, bk, "R8", xp, u["2"][1] + 5.08, "GND")
    # TEMP grounded (NTC disabled)
    bk.take("U2", "1", "GND")
    s.wire(u["1"], (u["1"][0] - 6.35, u["1"][1]))
    s.rail("GND", (u["1"][0] - 6.35, u["1"][1]))
    # die + EP grounds
    for p in ("3", "9"):
        bk.take("U2", p, "GND")
        s.wire(u[p], (u[p][0], u[p][1] + 3.81))
    s.wire((u["3"][0], u["3"][1] + 3.81), (u["9"][0], u["9"][1] + 3.81))
    s.wire((u["3"][0], u["3"][1] + 3.81), (u["3"][0], u["3"][1] + 6.35))
    s.junction((u["3"][0], u["3"][1] + 3.81))
    s.rail("GND", (u["3"][0], u["3"][1] + 6.35))
    # BAT node: cell + bulk cap + VBATT rail
    bk.take("U2", "5", "VBATT")
    xv = u["5"][0] + 20.32
    ybat = u["5"][1] - 8.89
    s.path(u["5"], (xv, u["5"][1]), (xv, ybat))
    s.rail("VBATT", (xv, ybat - 5.08))
    s.wire((xv, ybat), (xv, ybat - 5.08))
    s.wire((xv, ybat), (xv + 25.4, ybat))
    s.junction((xv, ybat))
    vdrop(s, cir, bk, "C17", xv + 12.7, ybat, "GND")
    s.junction((xv + 12.7, ybat))
    vdrop(s, cir, bk, "BT1", xv + 25.4, ybat, "GND")
    for p, net in (("6", "CHRG_DONE"), ("7", "CHRG")):
        bk.take("U2", p, net)
        s.wire(u[p], (u[p][0] + 3.81, u[p][1]))
        s.glabel(net, (u[p][0] + 3.81, u[p][1]))
    s.note("CHRG / DONE are open-drain -> GPIO with internal pull-up "
           "(low = active); software owns the charge indicator.",
           x - 40.64, u["3"][1] + 20.32, 115.0)
    s.end()


def blk_sense(s, cir, bk, x, y):
    s.begin("Switch / battery sense -> ADC")
    s.glabel("SW_ON", (x - 10.16, y), rot=180, just="right")
    s.wire((x - 10.16, y), (x, y))
    s.wire((x, y), (x, y + 3.81))
    r11 = put(s, cir, "R11", x, y + 7.62)
    bk.take("R11", "1", "SW_ON")
    bk.take("R11", "2", "VBSENSE")
    node = (x, r11["2"][1] + 3.81)
    s.wire(r11["2"], node)
    r12 = put(s, cir, "R12", x, node[1] + 3.81)
    bk.take("R12", "1", "VBSENSE")
    bk.take("R12", "2", "GND")
    s.wire(node, r12["1"])
    s.wire(r12["2"], (x, r12["2"][1] + 3.81))
    s.rail("GND", (x, r12["2"][1] + 3.81))
    s.junction(node)
    s.wire(node, (x + 15.24, node[1]))
    vdrop(s, cir, bk, "C21", x + 15.24, node[1], "GND")
    s.junction((x + 15.24, node[1]))
    s.wire(node, (x - 10.16, node[1]))
    s.glabel("VBSENSE", (x - 10.16, node[1]), rot=180, just="right")
    s.note("1M:1M divider off SW_ON, the switch common (rev 2 — was "
           "VBATT). Switch ON: VBATT/2 battery telemetry as before. "
           "Switch OFF + USB: reads 0, telling firmware to show charge "
           "status instead of running the show. GPIO29/ADC3.",
           x - 22.86, r12["2"][1] + 12.7, 56.0)
    s.end()


def blk_ldo(s, cir, bk, x, y):
    s.begin("3V3 LDO — EN = slide switch OR USB (diode-OR, clamped)")
    u = put(s, cir, "U3", x, y)
    bk.take("U3", "6", "VSYS")   # rev 2: the system rail, not the cell
    # 20.32, not the old 15.24: rev 2 renamed this riser VSYS and gave D2's
    # clamp its own VBATT rail one column to the right, so the IN riser has
    # to step left far enough that the two rail labels do not collide (and
    # far enough that C18's branch clears the clamp riser entirely)
    xin = u["6"][0] - 20.32
    s.wire(u["6"], (xin, u["6"][1]))
    s.wire((xin, u["6"][1]), (xin, u["6"][1] - 7.62))
    s.rail("VSYS", (xin, u["6"][1] - 7.62))
    # 7.62 off the riser, which after the riser's own 5.08 step keeps C18
    # in the column it has always occupied (SW2's reference text sits there)
    s.wire((xin, u["6"][1] - 3.81), (xin - 7.62, u["6"][1] - 3.81))
    s.junction((xin, u["6"][1] - 3.81))
    vdrop(s, cir, bk, "C18", xin - 7.62, u["6"][1] - 3.81, "GND")
    # OUT
    bk.take("U3", "1", "3V3")
    xo = u["1"][0] + 15.24
    s.wire(u["1"], (xo, u["1"][1]))
    s.wire((xo, u["1"][1]), (xo, u["1"][1] - 7.62))
    s.rail("3V3", (xo, u["1"][1] - 7.62))
    s.wire((xo, u["1"][1] - 3.81), (xo + 12.7, u["1"][1] - 3.81))
    s.junction((xo, u["1"][1] - 3.81))
    vdrop(s, cir, bk, "C19", xo + 12.7, u["1"][1] - 3.81, "GND")
    for p in ("2", "5"):
        bk.take("U3", p, "")
        s.nc(u[p])
    for p in ("3", "EP"):
        bk.take("U3", p, "GND")
        s.wire(u[p], (u[p][0], u[p][1] + 3.81))
    s.wire((u["3"][0], u["3"][1] + 3.81), (u["EP"][0], u["EP"][1] + 3.81))
    s.wire((u["3"][0], u["3"][1] + 3.81), (u["3"][0], u["3"][1] + 6.35))
    s.junction((u["3"][0], u["3"][1] + 3.81))
    s.rail("GND", (u["3"][0], u["3"][1] + 6.35))
    # EN = SW_ON OR VBUS. D2 (BAT54SW series pair) stands VERTICALLY
    # beside U3 — the strip further left belongs to C18 and the IN
    # riser. SW_ON enters pin 1 from below, the clamp cathode (pin 2)
    # rises to VBATT above, and the midpoint (pin 3) taps right, in
    # line with U3's EN pin. Diode 1 lifts EN to VBATT-0.2 when the
    # switch is on; diode 2 clamps EN to VBATT+Vf because NCP730 abs
    # max V_EN is only (V_IN + 0.3). The VBUS half of the OR (R18) has
    # its own block — see "USB wake"; the nets meet on the PWR_EN
    # global label.
    bk.take("U3", "4", "PWR_EN")
    u4 = u["4"]
    d2 = put(s, cir, "D2", u4[0] - 13.97, u4[1], rot=90,
             ref_off=(-11.43, 3.3))
    bk.take("D2", "1", "SW_ON")
    bk.take("D2", "2", "VBATT")
    bk.take("D2", "3", "PWR_EN")
    # the clamp cathode used to join the IN riser 1.27 to the left, back
    # when IN was VBATT too; rev 2's power path made that riser VSYS, so
    # the clamp needs a VBATT rail of its own. Still legal, and still the
    # conservative choice: V_EN max is V_IN + 0.3 and VSYS >= VBATT always.
    s.wire(d2["2"], (d2["2"][0], d2["2"][1] - 11.43))
    s.rail("VBATT", (d2["2"][0], d2["2"][1] - 11.43))
    s.wire(d2["3"], u4)
    # R17 pulldown hangs off the EN run (100k: EN has an internal <=1uA
    # pull-up to VIN, so a 1M pulldown could fail to turn the LDO off);
    # the PWR_EN glabel stubs off R17's riser
    s.junction((u4[0] - 6.35, u4[1]))
    s.wire((u4[0] - 6.35, u4[1]), (u4[0] - 6.35, u4[1] + 2.54))
    # drop=6.35 + the one-step-left column push the GND rail's text
    # clear of U3's value text below the box
    vdrop(s, cir, bk, "R17", u4[0] - 6.35, u4[1] + 2.54, "GND", drop=6.35)
    s.junction((u4[0] - 6.35, u4[1] + 1.27))
    s.wire((u4[0] - 6.35, u4[1] + 1.27), (u4[0] - 7.62, u4[1] + 1.27))
    s.glabel("PWR_EN", (u4[0] - 7.62, u4[1] + 1.27), rot=180,
             just="right", size=1.0)
    # slide switch: common is SW_ON now, clean VBATT/GND both positions
    s.wire(d2["1"], (d2["1"][0], d2["1"][1] + 2.54))
    sw = put(s, cir, "SW2", u4[0] - 38.1, u4[1] + 10.16)
    bk.take("SW2", "2", "SW_ON")
    bk.take("SW2", "1", "VBATT")
    bk.take("SW2", "3", "GND")
    s.wire(sw["2"], (d2["1"][0], sw["2"][1]))
    s.label("SW_ON", (sw["2"][0] + 2.54, sw["2"][1]), size=1.0)
    s.path(sw["1"], (sw["1"][0] - 2.54, sw["1"][1]),
           (sw["1"][0] - 2.54, sw["1"][1] - 5.08))
    s.rail("VBATT", (sw["1"][0] - 2.54, sw["1"][1] - 5.08))
    s.wire(sw["3"], (sw["3"][0] - 2.54, sw["3"][1]))
    s.rail("GND", (sw["3"][0] - 2.54, sw["3"][1]))
    s.end()


def blk_vbussense(s, cir, bk, x, y):
    """VBUS presence tap -> ADC1. Added with the rev-3 netlist but never
    drawn until now, which is why build.py --only schematic was failing."""
    s.begin("USB cable present — 10k:10k tap on VBUS -> ADC1")
    s.rail("VBUS", (x, y - 7.62))
    s.wire((x, y - 7.62), (x, y - 3.81))
    r19 = put(s, cir, "R19", x, y)
    bk.take("R19", "1", "VBUS")
    bk.take("R19", "2", "VBUS_SENSE")
    node = (x, r19["2"][1] + 3.81)
    s.wire(r19["2"], node)
    r20 = put(s, cir, "R20", x, node[1] + 3.81)
    bk.take("R20", "1", "VBUS_SENSE")
    bk.take("R20", "2", "GND")
    s.wire(node, r20["1"])
    s.wire(r20["2"], (x, r20["2"][1] + 3.81))
    s.rail("GND", (x, r20["2"][1] + 3.81))
    s.junction(node)
    s.wire(node, (x - 10.16, node[1]))
    s.glabel("VBUS_SENSE", (x - 10.16, node[1]), rot=180, just="right")
    s.note("CHRG and DONE both release at termination, so they cannot tell "
           "'unplugged' from 'plugged in and full'. 10k:10k, not the "
           "100k/1M used elsewhere: PWR_EN backfeeds through R18 and would "
           "float this node high, so the tap has to be stiff enough to "
           "swamp it (0.33V no cable, 2.2-2.75V with one). That is also "
           "what holds Q2's gate low enough to keep the battery path on.",
           x - 25.4, r20["2"][1] + 13.97, 96.0)
    s.end()


def blk_path(s, cir, bk, x, y):
    """(x, y) is Q2's centre: gate to the left, VBATT above, VSYS below."""
    s.begin("power path — VBUS runs the board when a cable is in")
    q2 = put(s, cir, "Q2", x, y)
    bk.take("Q2", "1", "PATH_GATE")
    bk.take("Q2", "2", "VSYS")
    bk.take("Q2", "3", "VBATT")
    xs, xg = x + 2.54, x - 15.24
    ys = y + 17.78
    # drain up to the cell, source down to the system rail
    s.wire(q2["3"], (xs, y - 15.24))
    s.rail("VBATT", (xs, y - 15.24))
    s.wire(q2["2"], (xs, ys))
    # gate: R22 up to VBUS, R21 down to GND. Off when a cable holds the
    # gate at VBUS (Vgs = +0.25V against VSYS); on when R19/R20 hold the
    # dead VBUS node at <=0.65V (Vgs = -2.4V at a 3.0V cell).
    s.wire(q2["1"], (xg, y))
    s.junction((xg, y))
    s.label("PATH_GATE", (xg, y), rot=180, just="right", size=1.0)
    r22 = put(s, cir, "R22", xg, y - 7.62)
    bk.take("R22", "1", "VBUS")
    bk.take("R22", "2", "PATH_GATE")
    s.wire(r22["2"], (xg, y))
    s.wire(r22["1"], (xg, y - 15.24))
    s.rail("VBUS", (xg, y - 15.24))
    # spelled out rather than vdrop()'d: R21's automatic reference text
    # lands to its right, on top of the PATH_GATE label
    r21 = put(s, cir, "R21", xg, y + 3.81, ref_off=(-9.4, 0.0))
    bk.take("R21", "1", "PATH_GATE")
    bk.take("R21", "2", "GND")
    s.wire(r21["2"], (xg, y + 11.43))
    s.rail("GND", (xg, y + 11.43))
    # VBUS -> VSYS through D3, then the VSYS row runs east past C29
    # text pushed below the part: the default spot above it lands on R21's
    # GND drop, and the row itself is the anode wire
    d3 = put(s, cir, "D3", xs - 20.32, ys, ref_off=(-6.0, 4.0))
    bk.take("D3", "2", "VBUS")
    bk.take("D3", "1", "VSYS")
    s.wire(d3["2"], (xs - 33.02, ys))
    s.wire((xs - 33.02, ys), (xs - 33.02, ys - 7.62))
    s.rail("VBUS", (xs - 33.02, ys - 7.62))
    s.wire(d3["1"], (xs, ys))
    s.junction((xs, ys))
    s.wire((xs, ys), (xs + 25.4, ys))
    s.junction((xs + 12.7, ys))
    vdrop(s, cir, bk, "C29", xs + 12.7, ys, "GND")
    s.wire((xs + 25.4, ys), (xs + 25.4, ys - 7.62))
    s.rail("VSYS", (xs + 25.4, ys - 7.62))
    s.note("Rev 2: VBATT is the cell alone, VSYS runs the board, so the "
           "charger's whole 41mA reaches the cell in either switch "
           "position. Q2's SOURCE is VSYS and its drain VBATT — a P-FET "
           "body diode conducts drain->source, so that way round it blocks "
           "USB from back-feeding the cell past the charger.",
           x - 48.26, ys + 20.32, 104.0)
    s.end()


def blk_shift(s, cir, bk, x, y):
    """(x, y) is Q3's centre: LED_DATA in from the left, LED_D0 out up."""
    s.begin("LED data level shifter — open-drain into the ring")
    q3 = put(s, cir, "Q3", x, y)
    bk.take("Q3", "1", "LED_DATA")
    bk.take("Q3", "2", "GND")
    bk.take("Q3", "3", "LED_D0")
    s.wire(q3["1"], (x - 15.24, y))
    s.glabel("LED_DATA", (x - 15.24, y), rot=180, just="right")
    s.wire(q3["2"], (x + 2.54, y + 12.7))
    s.rail("GND", (x + 2.54, y + 12.7))
    node = (x + 2.54, y - 15.24)
    s.wire(q3["3"], node)
    s.junction(node)
    s.wire(node, (x + 17.78, node[1]))
    s.glabel("LED_D0", (x + 17.78, node[1]))
    r23 = put(s, cir, "R23", x + 2.54, y - 22.86)
    bk.take("R23", "1", "VLED")
    bk.take("R23", "2", "LED_D0")
    s.wire(r23["2"], node)
    s.wire(r23["1"], (x + 2.54, y - 30.48))
    s.rail("VLED", (x + 2.54, y - 30.48))
    s.note("The ring's VIH is 0.7*VLED. On the cell that peaked at 2.94V "
           "and the MCU drove pixel 1 directly; on VSYS it is 3.29V (3.5V "
           "at a 5.25V port), past anything a 3.3V pad can output. Q3 "
           "inverts into R23's pull-up, so the swing is a full VLED rail "
           "whatever VLED is — 3.0V cell or 5.0V cable. Only pixel 1 needs "
           "it; every DI after that is driven by the previous DO. Firmware "
           "must set gpio_set_outover(LED_DATA, GPIO_OVERRIDE_INVERT) — the "
           "pad override sits after the PIO, so the NeoPixel program is "
           "untouched.",
           x - 20.32, y + 20.32, 90.0)
    s.end()


def blk_en(s, cir, bk, x, y):
    s.begin("USB wake — VBUS feeds EN through R18")
    s.glabel("PWR_EN", (x - 10.16, y), rot=180, just="right")
    s.wire((x - 10.16, y), (x, y))
    r18 = put(s, cir, "R18", x, y - 3.81)
    bk.take("R18", "1", "VBUS")
    bk.take("R18", "2", "PWR_EN")
    s.wire(r18["1"], (x, r18["1"][1] - 2.54))
    s.rail("VBUS", (x, r18["1"][1] - 2.54))
    s.note("Rev 2: USB boots the board even with SW2 off. Against "
           "R17's pulldown EN sits at ~VBUS/2, and D2's second diode "
           "clamps it to VBATT+Vf (NCP730 abs max V_EN is VIN+0.3, "
           "even during precharge of a dead cell). Firmware then sees "
           "SW_ON=0 on the sense divider and shows charge status "
           "instead of running the show.",
           x - 25.4, y + 7.62, 60.0)
    s.end()


def blk_light(s, cir, bk, x, y):
    s.begin("Ambient light sensor -> ADC0 (rev 2)")
    q = put(s, cir, "Q1", x, y)
    bk.take("Q1", "1", "3V3")
    s.wire(q["1"], (q["1"][0], q["1"][1] - 5.08))
    s.rail("3V3", (q["1"][0], q["1"][1] - 5.08))
    bk.take("Q1", "2", "LIGHT")
    # node sits 8.89 below the emitter: Q1's value text lands just under
    # the box, and a shallower node wire runs straight through it
    node = (q["2"][0], q["2"][1] + 8.89)
    s.wire(q["2"], node)
    s.wire(node, (node[0] + 12.7, node[1]))
    vdrop(s, cir, bk, "C26", node[0] + 12.7, node[1], "GND")
    s.junction((node[0] + 12.7, node[1]))
    s.wire(node, (node[0] - 10.16, node[1]))
    s.glabel("LIGHT", (node[0] - 10.16, node[1]), rot=180, just="right")
    s.junction(node)
    vdrop(s, cir, bk, "R16", node[0], node[1], "GND")
    s.note("ALS-PT19 visible-light phototransistor; 22k load -> ~0.33V "
           "@ 100 lux, saturates ~900 lux. Reads on GPIO26/ADC0.",
           x - 20.32, node[1] + 22.86, 44.0)
    s.end()


def blk_loadsw(s, cir, bk, x, y):
    s.begin("VLED high-side load switch (LEDs draw zero when off)")
    u = put(s, cir, "U4", x, y)
    bk.take("U4", "A2", "VSYS")   # rev 2: LEDs run off the cable when in
    s.wire(u["A2"], (u["A2"][0] - 10.16, u["A2"][1]))
    s.wire((u["A2"][0] - 10.16, u["A2"][1]),
           (u["A2"][0] - 10.16, u["A2"][1] - 6.35))
    s.rail("VSYS", (u["A2"][0] - 10.16, u["A2"][1] - 6.35))
    bk.take("U4", "A1", "VLED")
    xo = u["A1"][0] + 12.7
    s.wire(u["A1"], (xo, u["A1"][1]))
    s.wire((xo, u["A1"][1]), (xo, u["A1"][1] - 6.35))
    s.rail("VLED", (xo, u["A1"][1] - 6.35))
    s.wire((xo, u["A1"][1]), (xo + 12.7, u["A1"][1]))
    s.junction((xo, u["A1"][1]))
    vdrop(s, cir, bk, "C20", xo + 12.7, u["A1"][1], "GND")
    bk.take("U4", "B1", "GND")
    s.wire(u["B1"], (u["B1"][0], u["B1"][1] + 3.81))
    s.rail("GND", (u["B1"][0], u["B1"][1] + 3.81))
    bk.take("U4", "B2", "LED_EN")
    xn = u["B2"][0] - 10.16
    s.wire(u["B2"], (xn, u["B2"][1]))
    s.junction((xn, u["B2"][1]))
    vdrop(s, cir, bk, "R10", xn, u["B2"][1], "GND")
    s.wire((xn, u["B2"][1]), (xn - 7.62, u["B2"][1]))
    s.glabel("LED_EN", (xn - 7.62, u["B2"][1]), rot=180, just="right")
    s.note("R10 holds the switch off until firmware drives LED_EN high.",
           x - 25.4, u["B1"][1] + 15.24, 76.0)
    s.end()


def blk_bank(s, cir, bk, title, refs, x, y, rail, pitch=12.7, note=None,
             rows=1):
    """Rows of identical 2-pin parts strung between a rail and ground."""
    s.begin(title)
    per = math.ceil(len(refs) / rows)
    ybot = y
    for r in range(rows):
        chunk = refs[r * per:(r + 1) * per]
        if not chunk:
            continue
        xs = [x + i * pitch for i in range(len(chunk))]
        ytop = y + r * 27.94
        ybot = ytop + 15.24
        for xi, ref in zip(xs, chunk):
            p = put(s, cir, ref, xi, ytop + 7.62, hide_value=True,
                    ref_off=(1.9, -4.0))
            bk.take(ref, "1", rail)
            bk.take(ref, "2", "GND")
            s.wire((xi, ytop), p["1"])
            s.wire(p["2"], (xi, ybot))
        s.wire((xs[0], ytop), (xs[-1], ytop))
        s.wire((xs[0], ybot), (xs[-1], ybot))
        for xi in xs[1:-1]:
            s.junction((xi, ytop))
            s.junction((xi, ybot))
        xe = xs[0] if r % 2 == 0 else xs[-1]
        s.wire((xe, ytop), (xe, ytop - 3.81))
        s.rail(rail, (xe, ytop - 3.81))
        s.wire((xe, ybot), (xe, ybot + 3.81))
        s.rail("GND", (xe, ybot + 3.81))
    if note:
        s.note(note, x, ybot + 12.7, min(160.0, per * pitch))
    s.end()


def blk_mcu(s, cir, bk, cx, cy):
    """MCU + everything wired straight to it: flash, crystal, VREG, BOOTSEL,
    RUN pull-up and the SWD test points."""
    s.begin("RP2350A")
    # both texts go above the chip: the bottom-left corner is where the
    # ground symbols land
    hw, hh = s.defs["mcu"].extent
    u = put(s, cir, "U1", cx, cy, ref_off=(-hw, -hh - 9.0))
    # --- top edge: 3V3 rail and the VDD_CORE feedback rail ---
    v33 = ["1", "11", "20", "30", "38", "45", "54", "53", "44"]
    yr = u["1"][1] - 7.62
    for p in v33:
        bk.take("U1", p, "3V3")
        s.wire(u[p], (u[p][0], yr))
    s.wire((u[v33[0]][0], yr), (u[v33[-1]][0], yr))
    for p in v33[1:-1]:
        s.junction((u[p][0], yr))
    s.wire((u[v33[0]][0], yr), (u[v33[0]][0], yr - 3.81))
    s.junction((u[v33[0]][0], yr))
    s.rail("3V3", (u[v33[0]][0], yr - 3.81))
    core = ["6", "23", "39"]
    yc = u["6"][1] - 12.7
    for p in core:
        bk.take("U1", p, "VDD_CORE")
        s.wire(u[p], (u[p][0], yc))
    s.wire((u[core[0]][0], yc), (u[core[-1]][0], yc))
    s.junction((u[core[1]][0], yc))
    s.wire((u[core[-1]][0], yc), (u[core[-1]][0], yc - 3.81))
    s.junction((u[core[-1]][0], yc))
    s.rail("VDD_CORE", (u[core[-1]][0], yc - 3.81))
    # --- bottom edge grounds ---
    # EP and VREG_PGND are one node — join them under the chip and take a
    # single ground symbol, or the two "GND" labels merge into one word
    for p in ("61", "47"):
        bk.take("U1", p, "GND")
        s.wire(u[p], (u[p][0], u[p][1] + 3.81))
    s.wire((u["61"][0], u["61"][1] + 3.81), (u["47"][0], u["47"][1] + 3.81))
    s.junction((u["47"][0], u["47"][1] + 3.81))
    s.rail("GND", (u["47"][0], u["47"][1] + 3.81))
    # --- unused GPIOs ---
    for p, net in cir.components["U1"].pins.items():
        if net == "":
            bk.take("U1", p, "")
            s.nc(u[p])
    # --- used GPIOs out to the rest of the sheet ---
    for p in ("29", "3", "9", "15", "12", "31", "42", "40", "41", "43"):
        net = bk.take("U1", p)
        s.wire(u[p], (u[p][0] + 6.35, u[p][1]))
        s.glabel(net, (u[p][0] + 6.35, u[p][1]))
    # --- USB ---
    for p in ("51", "52"):
        net = bk.take("U1", p)
        s.wire(u[p], (u[p][0] - 6.35, u[p][1]))
        s.glabel(net, (u[p][0] - 6.35, u[p][1]), rot=180, just="right")
    s.end(pad=3.0)
    return u


def blk_vreg(s, cir, bk, u):
    s.begin("RP2350 core buck regulator (ds §6.3.8)")
    # VIN
    bk.take("U1", "49", "3V3")
    yv = u["49"][1] + 33.02
    s.wire(u["49"], (u["49"][0], yv))
    s.wire((u["49"][0], yv), (u["49"][0] + 22.86, yv))
    s.junction((u["49"][0] + 12.7, yv))
    s.wire((u["49"][0] + 22.86, yv), (u["49"][0] + 22.86, yv - 5.08))
    vdrop(s, cir, bk, "C11", u["49"][0] + 12.7, yv, "GND")
    s.rail("3V3", (u["49"][0] + 22.86, yv - 5.08))
    # AVDD RC filter — runs below C11's ground symbol, not through it
    bk.take("U1", "46", "VREG_AVDD")
    ya = u["46"][1] + 55.88
    s.path(u["46"], (u["46"][0], ya), (u["46"][0] + 25.4, ya))
    s.label("VREG_AVDD", (u["46"][0] + 2.54, ya), size=1.0)
    r13 = put(s, cir, "R13", u["46"][0] + 29.21, ya, rot=270)
    bk.take("R13", "2", "VREG_AVDD")
    bk.take("R13", "1", "3V3")
    s.wire((u["46"][0] + 25.4, ya), r13["2"])
    s.wire(r13["1"], (r13["1"][0] + 5.08, r13["1"][1]))
    s.rail("3V3", (r13["1"][0] + 5.08, r13["1"][1]))
    s.junction((u["46"][0] + 12.7, ya))
    s.wire((u["46"][0] + 12.7, ya), (u["46"][0] + 12.7, ya))
    vdrop(s, cir, bk, "C22", u["46"][0] + 12.7, ya, "GND")
    # LX -> inductor -> VDD_CORE, FB tied back
    bk.take("U1", "48", "VREG_LX")
    yl = u["48"][1] + 30.48
    s.wire(u["48"], (u["48"][0], yl))
    l1 = put(s, cir, "L1", u["48"][0], yl + 3.81, rot=180,
             ref_off=(-13.97, -2.0))
    bk.take("L1", "2", "VREG_LX")
    bk.take("L1", "1", "VDD_CORE")
    node = (l1["1"][0], l1["1"][1] + 5.08)
    s.wire(l1["1"], node)
    bk.take("U1", "50", "VDD_CORE")
    s.path(u["50"], (u["50"][0], node[1] + 7.62), (node[0], node[1] + 7.62),
           node)
    s.junction(node)
    # VDD_CORE bus runs left only: the FB return comes down on the right and
    # would be crossed by anything hung on that side.
    core = (("C12", -10.16), ("C13", -20.32), ("C5", -30.48),
            ("C6", -40.64))
    end = node[0] - 50.8
    s.wire(node, (end, node[1]))
    s.rail("VDD_CORE", (end, node[1] - 3.81))
    s.wire((end, node[1]), (end, node[1] - 3.81))
    for ref, dx in core:
        s.junction((node[0] + dx, node[1]))
        vdrop(s, cir, bk, ref, node[0] + dx, node[1], "GND")
    s.label("VREG_LX", (u["48"][0], yl - 2.54), rot=90, size=1.0)
    s.note("L1 dot on the VOUT (pad 1) side — ds Fig 23. C11 CIN; C12 COUT "
           "at L1; C13 the 2nd 4u7 at DVDD 23 (§6.3.8.1). C5/C6 are the 100n "
           "HF pair §6.1.3 wants on the two DVDD pins nearest the regulator "
           "— they already sat there, netted to 3V3. R13+C22 filter "
           "VREG_AVDD.",
           u["48"][0] - 55.88, node[1] + 25.4, 66.0)
    s.end()


def blk_flash(s, cir, bk, u):
    s.begin("QSPI flash (BOOTSEL strap on /CS)")
    qspi = [("60", "1"), ("56", "6"), ("57", "5"), ("59", "2"), ("58", "3"),
            ("55", "7")]
    xr = u["56"][0] - 50.8
    f = put(s, cir, "U7", xr - 10.16, q((u["60"][1] + u["55"][1]) / 2.0))
    for mp, fp in qspi:
        net = bk.take("U1", mp)
        bk.take("U7", fp, net)
        assert f[fp][1] == u[mp][1], f"flash {fp} not aligned with MCU {mp}"
        s.wire(f[fp], u[mp])
        s.label(net, (u[mp][0] - 16.51, u[mp][1]), size=1.0)
    bk.take("U7", "8", "3V3")
    x3 = f["8"][0] - 7.62
    s.path(f["8"], (x3, f["8"][1]), (x3, f["8"][1] - 6.35))
    s.rail("3V3", (x3, f["8"][1] - 6.35))
    s.junction((x3, f["8"][1]))
    s.wire((x3, f["8"][1]), (x3 - 12.7, f["8"][1]))
    vdrop(s, cir, bk, "C25", x3 - 12.7, f["8"][1], "GND")
    xg = f["4"][0] - 7.62
    for p in ("4", "9"):
        bk.take("U7", p, "GND")
        s.wire(f[p], (xg, f[p][1]))
    s.wire((xg, f["4"][1]), (xg, f["9"][1]))
    s.junction((xg, f["9"][1]))
    s.wire((xg, f["9"][1]), (xg, f["9"][1] + 3.81))
    s.rail("GND", (xg, f["9"][1] + 3.81))
    # BOOTSEL strap rises off the /CS wire, which is the top of the bus, so
    # it never has to get past the other five QSPI lines
    xb = u["60"][0] - 25.4
    s.junction((xb, u["60"][1]))
    r3 = put(s, cir, "R3", xb, u["60"][1] - 3.81, rot=180)
    bk.take("R3", "1", "BOOTSEL")
    bk.take("R3", "2", "BOOTSEL_SW")
    s.wire((xb, u["60"][1]), r3["1"])
    yb = r3["2"][1]
    # the button lies flat above the bus: a vertical switch here would put
    # its ground pins straight onto the QSPI lines
    sw = put(s, cir, "SW1", xb - 20.32, yb, rot=180, ref_off=(-6.35, -9.4))
    # Only the diagonal pair 1/4 is netted, so the strap is right whichever
    # way the part pairs its terminals — see the note in circuit.py. 2 and 3
    # ride along with their own blade and are drawn as no-connects.
    bk.take("SW1", "1", "BOOTSEL_SW")
    bk.take("SW1", "4", "GND")
    for pin in ("2", "3"):
        bk.take("SW1", pin, "")
        s.nc(sw[pin])
    xj = sw["1"][0] + 5.08
    s.path(sw["1"], (xj, sw["1"][1]), (xj, yb), r3["2"])
    s.label("BOOTSEL_SW", (xj + 1.27, yb), size=1.0)
    s.wire(sw["4"], (sw["4"][0] - 5.08, sw["4"][1]))
    s.rail("GND", (sw["4"][0] - 5.08, sw["4"][1]))
    s.note("Pico-style: QSPI_SS is both the flash /CS and the BOOTSEL "
           "strap.", f["8"][0] - 20.32, f["9"][1] + 17.78, 76.0)
    s.end()


def blk_xtal(s, cir, bk, u):
    s.begin("12MHz crystal")
    bk.take("U1", "21", "XIN")
    bk.take("U1", "22", "XOUT")
    xy = u["21"][0] - 48.26
    y1 = put(s, cir, "Y1", xy, u["21"][1] + 3.81, rot=270)
    bk.take("Y1", "1", "XIN")
    bk.take("Y1", "3", "XTAL_R")
    bk.take("Y1", "2", "GND")
    bk.take("Y1", "4", "GND")
    assert y1["1"][1] == u["21"][1]
    s.wire(y1["1"], u["21"])
    s.label("XIN", (y1["1"][0] + 10.16, y1["1"][1]), size=1.0)
    s.wire(y1["2"], (y1["2"][0] - 6.35, y1["2"][1]))
    s.rail("GND", (y1["2"][0] - 6.35, y1["2"][1]))
    # load caps hang to the left, clear of the crystal body
    s.path(y1["1"], (y1["1"][0], y1["1"][1] - 2.54),
           (y1["1"][0] - 20.32, y1["1"][1] - 2.54))
    s.junction(y1["1"])
    vdrop(s, cir, bk, "C14", y1["1"][0] - 20.32, y1["1"][1] - 2.54, "GND")
    s.path(y1["3"], (y1["3"][0], y1["3"][1] + 10.16),
           (y1["3"][0] - 35.56, y1["3"][1] + 10.16))
    vdrop(s, cir, bk, "C15", y1["3"][0] - 35.56, y1["3"][1] + 10.16, "GND")
    s.junction(y1["3"])
    # XOUT returns through the series resistor, under the XIN wire
    r1 = put(s, cir, "R1", y1["3"][0] + 12.7, y1["3"][1], rot=90)
    bk.take("R1", "1", "XTAL_R")
    bk.take("R1", "2", "XOUT")
    s.wire(y1["3"], r1["1"])
    s.label("XTAL_R", (y1["3"][0] + 1.27, y1["3"][1]), size=1.0)
    s.path(r1["2"], (u["22"][0] - 7.62, r1["2"][1]),
           (u["22"][0] - 7.62, u["22"][1]), u["22"])
    s.label("XOUT", (u["22"][0] - 6.35, u["22"][1]), size=1.0)
    s.note("ABM8-272-T3, CL 10pF / ESR<=50R — the 15p caps and R1 are "
           "matched to it; do not retune.",
           y1["1"][0] - 40.64, y1["3"][1] + 33.02, 74.0)
    s.end()


def blk_sys(s, cir, bk, u):
    s.begin("RUN / SWD")
    bk.take("U1", "26", "RUN")
    xn = u["26"][0] - 20.32
    s.wire(u["26"], (xn, u["26"][1]))
    r2 = put(s, cir, "R2", xn, u["26"][1] - 3.81, rot=180)
    bk.take("R2", "1", "RUN")
    bk.take("R2", "2", "3V3")
    s.wire(r2["2"], (xn, r2["2"][1] - 3.81))
    s.rail("3V3", (xn, r2["2"][1] - 3.81))
    s.junction((xn, u["26"][1]))
    s.label("RUN", (xn + 5.08, u["26"][1]), size=1.0)
    # values are hidden: each stub already carries its net label
    tp1 = put(s, cir, "TP1", xn - 12.7, u["26"][1], rot=90, hide_value=True)
    bk.take("TP1", "1", "RUN")
    s.wire((xn, u["26"][1]), tp1["1"])
    for ref, pin in (("TP2", "24"), ("TP3", "25")):
        net = bk.take("U1", pin)
        bk.take(ref, "1", net)
        tp = put(s, cir, ref, xn - 12.7, u[pin][1], rot=90,
                 hide_value=True)
        s.wire(tp["1"], u[pin])
        s.label(net, (xn, u[pin][1]), size=1.0)
    s.end()


def blk_imu(s, cir, bk, x, y):
    s.begin("IMU — LSM6DS3TR-C on I2C1 (addr 0x6A)")
    u = put(s, cir, "U6", x, y)
    # rails
    for p in ("8", "5"):
        bk.take("U6", p, "3V3")
        s.wire(u[p], (u[p][0], u[p][1] - 5.08))
    s.wire((u["8"][0], u["8"][1] - 5.08), (u["5"][0], u["5"][1] - 5.08))
    s.wire((u["8"][0], u["8"][1] - 5.08), (u["8"][0], u["8"][1] - 8.89))
    s.junction((u["8"][0], u["8"][1] - 5.08))
    s.rail("3V3", (u["8"][0], u["8"][1] - 8.89))
    for p in ("6", "7"):
        bk.take("U6", p, "GND")
        s.wire(u[p], (u[p][0], u[p][1] + 3.81))
    s.wire((u["6"][0], u["6"][1] + 3.81), (u["7"][0], u["7"][1] + 3.81))
    s.wire((u["6"][0], u["6"][1] + 3.81), (u["6"][0], u["6"][1] + 6.35))
    s.junction((u["6"][0], u["6"][1] + 3.81))
    s.rail("GND", (u["6"][0], u["6"][1] + 6.35))
    # mode straps on the right: CS high selects I2C, SDx/SCx idle the
    # unused aux master. All three go to VDDIO = 3V3.
    xs = u["12"][0] + 15.24
    for p in ("12", "2", "3"):
        bk.take("U6", p, "3V3")
        s.wire(u[p], (xs, u[p][1]))
    s.wire((xs, u["12"][1]), (xs, u["3"][1]))
    s.wire((xs, u["12"][1]), (xs, u["12"][1] - 5.08))
    s.junction((xs, u["12"][1]))
    s.junction((xs, u["2"][1]))
    s.rail("3V3", (xs, u["12"][1] - 5.08))
    bk.take("U6", "1", "GND")
    s.wire(u["1"], (u["1"][0] + 6.35, u["1"][1]))
    s.rail("GND", (u["1"][0] + 6.35, u["1"][1]))
    for p in ("9", "10", "11"):
        bk.take("U6", p, "")
        s.nc(u[p])
    # I2C + interrupt, with the bus pull-ups
    # Both pull-ups stand above the two bus lines, and SDA (the upper line)
    # stops short of SCL's resistor so no wire is drawn across a symbol.
    for p, ref, dx, dl in (("14", "R14", 15.24, 17.78),
                           ("13", "R15", 33.02, 43.18)):
        net = bk.take("U6", p)
        xn = u[p][0] - dx
        s.wire(u[p], (xn, u[p][1]))
        s.junction((xn, u[p][1]))
        r = put(s, cir, ref, xn, u[p][1] - 3.81, rot=180)
        bk.take(ref, "1", net)
        bk.take(ref, "2", "3V3")
        s.wire(r["2"], (xn, r["2"][1] - 3.81))
        s.rail("3V3", (xn, r["2"][1] - 3.81))
        s.wire((xn, u[p][1]), (u[p][0] - dl, u[p][1]))
        s.glabel(net, (u[p][0] - dl, u[p][1]), rot=180, just="right")
    net = bk.take("U6", "4")
    s.wire(u["4"], (u["4"][0] - 7.62, u["4"][1]))
    s.glabel(net, (u["4"][0] - 7.62, u["4"][1]), rot=180, just="right")
    # decoupling — its own rail stubs, clear of the pin escapes on every side
    for i, ref in enumerate(("C23", "C24")):
        cx = u["7"][0] + 15.24 + i * 12.7
        ytop = u["7"][1] + 10.16
        s.rail("3V3", (cx, ytop - 3.81))
        s.wire((cx, ytop - 3.81), (cx, ytop))
        vdrop(s, cir, bk, ref, cx, ytop, "GND")
    s.note("CS/SDx/SCx -> VDDIO selects I2C mode 1 and idles the aux "
           "master; SDO/SA0 -> GND sets address 0x6A.",
           x - 27.94, u["6"][1] + 30.48, 96.0)
    s.end()


def blk_leds(s, cir, bk, design, x, y, per_row, pitch):
    n = design["leds"]["count"]
    s.begin(f"Addressable LED ring — {n} x SK6805-EC10 daisy chain")
    rows = [(r, list(range(r * per_row, min(n, (r + 1) * per_row))))
            for r in range((n + per_row - 1) // per_row)]
    # geometry comes from the symbol so a wider or taller LED box cannot
    # silently leave the chain wires hanging in mid-air
    ext_w = s.defs["led"].extent[0]
    ext_h = s.defs["led"].extent[1]
    gap = pitch - 2 * ext_w
    assert gap >= 7.62, (f"LED pitch {pitch} leaves only {gap:.1f}mm between "
                         "boxes — no room for the chain label")
    rowh = 2 * ext_h + 30.48
    for r, idx in rows:
        cy = y + r * rowh
        ytop, ybot = cy - ext_h - 5.08, cy + ext_h + 5.08
        first = None
        for k, i in enumerate(idx):
            ref = f"LED{i + 1}"
            xi = x + k * pitch
            p = put(s, cir, ref, xi, cy, hide_value=True,
                    ref_off=(-9.0, -8.4))
            if first is None:
                first = p
            bk.take(ref, "3", "VLED")
            bk.take(ref, "1", "GND")
            s.wire(p["3"], (xi, ytop))
            s.wire(p["1"], (xi, ybot))
            if k:
                s.junction((xi, ytop))
                s.junction((xi, ybot))
            din = bk.take(ref, "2")
            dout = bk.take(ref, "4")
            if k:
                prev = f"LED{idx[k - 1] + 1}"
                assert cir.components[prev].pins["4"] == din
                s.wire((xi - pitch + ext_w, cy), p["2"])
                s.label(din, (xi - pitch + ext_w + 1.27, cy), size=1.0)
            else:
                s.wire(p["2"], (xi - ext_w - 3.81, cy))
                s.glabel(din, (xi - ext_w - 3.81, cy), rot=180, just="right")
            if k == len(idx) - 1:
                if dout:
                    s.wire(p["4"], (xi + ext_w + 3.81, cy))
                    s.glabel(dout, (xi + ext_w + 3.81, cy))
                else:
                    s.nc(p["4"])
        xa, xb = x, x + (len(idx) - 1) * pitch
        s.wire((xa, ytop), (xb, ytop))
        s.wire((xa, ybot), (xb, ybot))
        s.wire((xa, ytop), (xa, ytop - 3.81))
        s.rail("VLED", (xa, ytop - 3.81))
        s.wire((xa, ybot), (xa, ybot + 3.81))
        s.rail("GND", (xa, ybot + 3.81))
    s.note("Chain runs LED1 -> LED%d in board order; each row break carries "
           "on through LED_D<n>. VLED is the switched battery rail, so the "
           "ring is dark until LED_EN goes high." % n,
           x - 8.89, y + (len(rows) - 1) * rowh + 24.13, 320.0, size=1.6)
    s.end()


# ---------------------------------------------------------------------------
def build_sheet(design, cir):
    s = Sch()
    s.defpassives()
    s.defbox("mcu", "RP2350A", mcu_sides())
    for part, sides in IC_SIDES.items():
        c = next(c for c in cir.components.values() if c.part == part)
        s.defbox(part, c.value, sides, min_w=IC_MIN_W.get(part, 0.0))
    bk = Book(cir.components)

    s.text("simple_earring — generated schematic", 16, 15, size=4.0,
           bold=True, frame=False)
    s.text(f"{len(cir.components)} components / {len(cir.nets)} nets / "
           f"{design['board']['layers']}-layer JLCPCB stackup.  "
           "Power rails (GND, 3V3, VBATT, VSYS, VLED, VBUS, VDD_CORE) are "
           "power "
           "symbols; only cross-block signals use global labels.  "
           "Generated from scripts/circuit.py — do not hand-edit; rebuild "
           "with `python3 build.py --only schematic`.",
           16, 21, size=1.8, frame=False)

    # Anchors are packed by hand against the measured block boxes; run with
    # SCH_LAYOUT=1 to print them when a netlist change resizes something.
    blk_usb(s, cir, bk, 30, 86)
    blk_charger(s, cir, bk, 58, 196)
    blk_sense(s, cir, bk, 164, 164)
    blk_ldo(s, cir, bk, 190, 59)
    blk_loadsw(s, cir, bk, 166, 122)
    blk_en(s, cir, bk, 272, 40)
    # rev-2 power path + its two satellites: the path sits under the
    # sense/load-switch column, the VBUS tap under the charger it taps,
    # and the level shifter beside the ring it drives
    blk_path(s, cir, bk, 189.3, 254.4)
    blk_vbussense(s, cir, bk, 620.4, 118.2)
    blk_shift(s, cir, bk, 450.3, 391.1)
    blk_light(s, cir, bk, 232, 176)
    blk_imu(s, cir, bk, 510, 137)

    mcx, mcy = 406.0, 136.0
    u = blk_mcu(s, cir, bk, mcx, mcy)
    blk_bank(s, cir, bk, "MCU decoupling — 100n on the 3V3 supply pins",
             [f"C{i}" for i in (1, 2, 3, 4, 7, 8, 9)], 466.0, 48.0, "3V3",
             note="IOVDD 38 and 1 share with C3/C4 — C5/C6 went to the "
                  "core rail (see the regulator block)")
    blk_vreg(s, cir, bk, u)
    blk_flash(s, cir, bk, u)
    blk_xtal(s, cir, bk, u)
    blk_sys(s, cir, bk, u)

    ring_caps = sorted((r for r in cir.components
                        if r.startswith("C") and r[1:].isdigit()
                        and int(r[1:]) >= 30), key=lambda r: int(r[1:]))
    blk_leds(s, cir, bk, design, 28.0, 336.0, 15, 26.67)
    blk_bank(s, cir, bk,
             "LED ring bypass — 100n VLED-GND, one per two LEDs",
             ring_caps, 448.0, 274.0, "VLED", pitch=11.43, rows=2,
             note="C30..C74, distributed around the ring next to their LEDs")

    bk.report()
    s.check_frames(verbose=bool(os.environ.get("SCH_LAYOUT")))
    clashes = s.check_text(verbose=bool(os.environ.get("SCH_LAYOUT")))
    if clashes and os.environ.get("SCH_ALLOW_TEXT_CLASH"):
        print(f"  WARNING: {len(clashes)} text clashes, emitted anyway")
        for m in clashes:
            print("    " + m)
        clashes = []
    assert not clashes, (f"{len(clashes)} text clashes — a reference, value "
                         "or note lands on a wire or on other text "
                         "(SCH_LAYOUT=1 lists them, SCH_ALLOW_TEXT_CLASH=1 "
                         "emits anyway):\n  " + "\n  ".join(clashes))
    placed = {r for r in s.refs if not r.startswith("#PWR")}
    missing = sorted(set(cir.components) - placed)
    assert not missing, f"components not drawn: {missing}"
    return s


# ---------------------------------------------------------------------------
def verify_netlist(cir):
    """Round-trip the finished sheet through KiCad and diff it against
    circuit.py. This is what makes the hand-authored layout trustworthy."""
    xml = OUT.parent / "earring-netlist.xml"
    r = subprocess.run(["kicad-cli", "sch", "export", "netlist",
                        "--format", "kicadxml", "-o", str(xml), str(OUT)],
                       capture_output=True, text=True)
    if r.returncode:
        print("  WARNING: netlist export failed, cannot verify:",
              r.stderr.strip())
        return False
    root = ET.parse(xml).getroot()
    got = defaultdict(set)
    for net in root.find("nets"):
        name = net.get("name")
        for node in net.findall("node"):
            got[name].add((node.get("ref"), node.get("pin")))
    want = defaultdict(set)
    for ref, c in cir.components.items():
        for pad, net in c.pins.items():
            if net:
                want[net].add((ref, pad))
    # KiCad names unlabelled nets by position; ours are all named, but the
    # comparison is by pin-set so auto-names on single-pin nets don't matter.
    got_sets = {frozenset(v): k for k, v in got.items() if len(v) > 1}
    problems = []
    for net, pins in sorted(want.items()):
        fs = frozenset(pins)
        if fs in got_sets:
            if got_sets[fs] != net:
                problems.append(f"net {net}: drawn as {got_sets[fs]!r}")
            continue
        drawn = got.get(net)
        if drawn is None:
            problems.append(f"net {net}: missing from the sheet entirely")
        else:
            extra = drawn - pins
            short = pins - drawn
            if extra:
                problems.append(f"net {net}: sheet also has "
                                + ", ".join(f"{a}.{b}" for a, b in sorted(extra)))
            if short:
                problems.append(f"net {net}: sheet is missing "
                                + ", ".join(f"{a}.{b}" for a, b in sorted(short)))
    xml.unlink(missing_ok=True)
    if problems:
        print("  NETLIST MISMATCH (sheet vs circuit.py):")
        for p in problems[:80]:
            print("   ", p)
        raise SystemExit(1)
    print(f"  netlist verified against circuit.py: {len(want)} nets match")
    return True


def main():
    design = load_design()
    cir = build_circuit(design)
    s = build_sheet(design, cir)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(s.render())
    print(f"wrote {OUT}: {len(s.defs)} symbols, {len(cir.components)} "
          f"components, {len(cir.nets)} nets, {len(s.frames)} blocks")

    pro = OUT.parent / "earring.kicad_pro"
    if pro.exists():
        import json
        d = json.loads(pro.read_text())
        want = [[str(SHEET_UUID), ""]]
        if d.get("sheets") != want:
            d["sheets"] = want
            pro.write_text(json.dumps(d, indent=2))
            print(f"  registered root sheet in {pro.name}")

    verify_netlist(cir)
    for args, label in (
            (["--exclude-drawing-sheet", "-o", str(OUT.parent)], "svg"),
            (["-o", str(OUT.parent / "earring-schematic.pdf")], "pdf")):
        r = subprocess.run(["kicad-cli", "sch", "export", label] + args
                           + [str(OUT)], capture_output=True, text=True)
        if r.returncode:
            print(f"  WARNING: {label} export failed: {r.stderr.strip()}")


if __name__ == "__main__":
    main()
