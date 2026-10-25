#!/usr/bin/env python3
"""Power-button / BOOTSEL testbench: scenarios x datasheet corners in ngspice.

The board-side netlist is NOT hand-copied: it is pulled from
scripts/circuit.py (the electrical source of truth) by reference designator,
so a value change there is a value change here. The one-button proposal is
the board as of 2026-10-24: one-button BOOTSEL, silicon D2/D3, TVS on the
button. The committed design before that (afabd86) is kept as a reference
patch (`afabd86()`) so its hazards stay demonstrable side by side.

    python3 design/sim/button/run.py                # every variant/scenario/corner
    python3 design/sim/button/run.py --quick        # typical corner only
    python3 design/sim/button/run.py -k bootsel     # scenarios whose name matches

Writes netlists + waveforms + report to out/sim/button/ (served by the
project dashboard), and exits non-zero if any check fails.

ngspice: --ngspice, else $NGSPICE, else `ngspice` on PATH, else the conda env
~/miniforge3/envs/spice (mamba create -n spice -c conda-forge ngspice).
"""
import argparse
import copy
import html
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "out" / "sim" / "button"
sys.path.insert(0, str(ROOT / "scripts"))
import circuit  # noqa: E402

# ---------------------------------------------------------------- netlist

# Everything on the battery / USB / latch / boot-strap nets. U1 is replaced
# by the behavioral RP2350 in mcu.lib; the rest of the board is a lumped
# 3V3 capacitance (summed from circuit.py below) and the MCU's load current.
POWER_REFS = [
    "BT1", "U2", "C16", "C17", "C28",            # cell, charger, bulk caps
    "Q2", "D3", "R21", "R22", "C29",              # rev-2 VBUS/VBATT ORing
    "R19", "R20",                                 # VBUS_SENSE divider (also Q2's gate)
    "U3", "C18", "C19", "R17", "R18", "D2",       # LDO + EN network
    "R11", "R12", "C21",                          # VBSENSE divider
    "SW2", "D6", "R30",                           # power button + ESD clamp
    "Q4", "R24", "Q5", "R25", "D4", "C27",        # soft latch
    "R26", "Q8", "R27", "R28", "C75", "D5",       # one-button: sense + hold timer
    "U8", "C77", "Q7", "C76", "R29", "Q6",        # one-button: BOOTSEL strap + RUN kick
    "R2", "R3",                                   # RUN pull-up, BOOTSEL strap R
]
ONE_BUTTON = ["D6", "R30", "R26", "Q8", "R27", "R28", "C75", "D5", "U8", "C77",
              "Q7", "C76", "R29", "Q6"]


def afabd86(c):
    """The committed design before 2026-10-24, rebuilt from today's circuit.py:
    SW1 BOOTSEL key, BTN_SENSE read through D4 A1 (pulled-up, active low),
    BAT54SW on D2, B5819WS on D3, no TVS. Kept so the hot self-start and the
    unkillable-hung-firmware hazard stay reproducible."""
    for r in ONE_BUTTON:
        del c.components[r]
    c.components["SW2"].pins["2"] = "BTN_N"
    c.components["D4"].pins["1"] = "BTN_SENSE"
    c.components["D2"].part = "or_diode_bat54"
    c.components["D3"].part = "sys_diode_b5819"
    c.components["Q4"].part = "oring_pfet"
    c.components["Q4"].value = "CJ2101"
    c.add("SW1", "bootsel_button", "BOOTSEL", {1: "BOOTSEL_SW", 2: "", 3: "", 4: "GND"})
    return c


def _d2_schottky(c):
    c.components["D2"].part = "or_diode_bat54"
    return c


def _d3_schottky(c):
    c.components["D3"].part = "sys_diode_b5819"
    return c


VARIANTS = {
    "board": lambda c: c,        # scripts/circuit.py as it stands
    "afabd86": afabd86,          # reference: the design this testbench found faults in
}
# the temperature sweep also puts each Schottky back on its own, to show
# that both silicon swaps are load-bearing
SWEEP_VARIANTS = {**VARIANTS, "D2_schottky": _d2_schottky, "D3_schottky": _d3_schottky}

SI = {"p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6, "G": 1e9}


def spice_val(v):
    """'4.7u' / '5.1k' / '1M' / '27' -> a SPICE-safe literal (M = mega!)."""
    m = re.fullmatch(r"([\d.]+)([pnumkMG]?)", v.strip())
    if not m:
        raise ValueError(f"unparseable value {v!r}")
    return f"{float(m.group(1)) * SI.get(m.group(2), 1):.6g}"


def node(n):
    return {"GND": "0", "": None}.get(n, n)


# B3U contact as a control-driven conductance: 100 mohm closed, 100 Mohm
# open (ds). (ngspice's hysteretic SW element came up CLOSED in the .ic
# operating point despite a 0V control, which latched the board on at t=0.)
SW_G = "(1e-8 + 10 * min(max(V({ctl}), 0), 1))"


def emit(comp):
    """One circuit.py Component -> SPICE line(s)."""
    p = {k: node(v) for k, v in comp.pins.items()}
    r, part = comp.ref, comp.part
    if part.startswith("r_"):
        return [f"R{r} {p['1']} {p['2']} {spice_val(comp.value)}"]
    if part.startswith("c_"):
        return [f"C{r} {p['1']} {p['2']} {spice_val(comp.value)}"]
    if part == "oring_pfet":                      # CJ2101: 1=G 2=S 3=D
        return [f"M{r} {p['3']} {p['1']} {p['2']} CJ2101"]
    if part == "lvl_nfet":                        # BSS138W: 1=G 2=S 3=D
        return [f"M{r} {p['3']} {p['1']} {p['2']} BSS138W",
                f"B{r}lk {p['3']} {p['2']} I = {{idss}} * exp((temper - 25) / 21.7)"
                f" * tanh(V({p['3']},{p['2']}) / 0.2)  $ IDSS (review F2)"]
    if part == "latch_pfet":                      # LBSS84WT1G: 1=G 2=S 3=D
        return [f"M{r} {p['3']} {p['1']} {p['2']} BSS84W"]
    if part == "cc_diode":                        # BAV70W: 1=A1 2=A2 3=K
        out = [f"D{r}a {p['1']} {p['3']} DSI", f"D{r}b {p['2']} {p['3']} DSI"]
        return [l for l in out if "None" not in l]
    if part == "or_diode":                        # BAV99W: 1=A1 2=K2 3=K1/A2
        return [f"D{r}a {p['1']} {p['3']} DSI", f"D{r}b {p['3']} {p['2']} DSI"]
    if part == "sys_diode":                       # 1N4007WS: 1=K 2=A
        return [f"X{r} {p['2']} {p['1']} D4007WS"]
    if part == "or_diode_bat54":                  # afabd86 D2, BAT54SW (same pinout)
        return [f"D{r}a {p['1']} {p['3']} BAT54", f"D{r}b {p['3']} {p['2']} BAT54"]
    if part == "sys_diode_b5819":                 # afabd86 D3, B5819WS: 1=K 2=A
        return [f"D{r} {p['2']} {p['1']} B5819"]
    if part == "si_diode":                        # 1N4148WS: 1=K 2=A
        return [f"D{r} {p['2']} {p['1']} DSI"]
    if part == "tvs_bidir":                       # PESD5V0S1BL, non-polar
        return [f"X{r} {p['1']} {p['2']} PESD5V0S1BL"]
    if part == "ldo":                             # NCP730: 1=OUT 3=GND 4=EN 6=IN
        return [f"X{r} {p['1']} {p['3']} {p['4']} {p['6']} NCP730"]
    if part == "charger":                         # LGS4056H: 4=VCC 5=BAT
        return [f"X{r} {p['4']} {p['5']} 0 LGS4056H"]
    if part == "battery_pads":                    # 1=+ 2=- : cell, see CELL
        return [f"X{r} {p['1']} {p['2']} CELL"]
    if part == "power_button":                    # SW2 1=GND 2=BTN_EXT
        return [f"B{r} {p['1']} {p['2']} I = V({p['1']},{p['2']}) * {SW_G.format(ctl='btn')}"]
    if part == "bootsel_button":                  # SW1 pads 1 and 4 (see circuit.py)
        return [f"B{r} {p['1']} {p['4']} I = V({p['1']},{p['4']}) * {SW_G.format(ctl='bsw')}"]
    if part == "logic_schmitt2":                  # 74LVC2G14: 1A-6Y, 3A-4Y, 5 VCC, 2 GND
        return [f"X{r}a {p['1']} {p['6']} {p['5']} {p['2']} LVC14",
                f"X{r}b {p['3']} {p['4']} {p['5']} {p['2']} LVC14"]
    raise KeyError(f"{r}: no simulation mapping for part {part!r}")


def board_netlist(variant):
    c = circuit.build_circuit()
    base = set(c.components)
    lumped_3v3 = sum(float(spice_val(x.value)) for x in c.components.values()
                     if x.part.startswith("c_") and "3V3" in x.pins.values()
                     and x.ref not in POWER_REFS)
    c = {**VARIANTS, **globals().get("SWEEP_VARIANTS", {})}[variant](copy.deepcopy(c))
    refs = [r for r in POWER_REFS if r in c.components]
    refs += [r for r in c.components if r not in POWER_REFS and r not in base]
    lines = [f"* --- from scripts/circuit.py, variant {variant} ---"]
    for r in refs:
        comp = c.components[r]
        lines.append(f"* {r} {comp.part} {comp.value}  {comp.pins}")
        lines += emit(comp)
    lines.append(f"Clump3v3 3V3 0 {lumped_3v3:.4g}  "
                 "$ every other 3V3 decap on the board, summed from circuit.py")
    # U1 pins on these nets
    u1 = c.components["U1"].pins
    nets = set(u1.values())
    for need in ("RUN", "BOOTSEL", "PWR_HOLD", "BTN_SENSE"):  # noqa
        assert need in nets, f"U1 has no {need} net — circuit.py changed?"
    lines.append("XU1 3V3 RUN BOOTSEL PWR_HOLD BTN_SENSE fwreq act smp bsel fwon RP2350")
    lines.append("CU7cs BOOTSEL 0 6p  $ W25Q16JV /CS input")
    return "\n".join(lines), c


# ---------------------------------------------------------------- stimulus

def pwl(points):
    """[(t, v), ...] -> PWL(...) with sorted, de-duplicated times."""
    pts, last = [], -1.0
    for t, v in points:
        t = max(t, last + 1e-9)
        pts.append(f"{t:.9g} {v:g}")
        last = t
    return "PWL(" + " ".join(pts) + ")"


def press(t0, t1, bounce=True):
    """Button closed from t0 to t1, with B3U bounce (<=5ms, ds) on both edges."""
    pts = [(0, 0), (t0, 0)]
    if bounce:
        for k, d in enumerate([0, 0.4e-3, 0.9e-3, 1.6e-3, 2.5e-3, 3.4e-3]):
            pts += [(t0 + d, 1 if k % 2 == 0 else 0), (t0 + d + 1e-6, 1 if k % 2 == 0 else 0)]
    pts += [(t0 + 4e-3, 1), (t1, 1)]
    if bounce:
        for k, d in enumerate([0, 0.5e-3, 1.2e-3, 2.0e-3]):
            pts += [(t1 + d, 0 if k % 2 == 0 else 1), (t1 + d + 1e-6, 0 if k % 2 == 0 else 1)]
    pts += [(t1 + 3e-3, 0)]
    return pts


def presses(spans, bounce=True):
    pts = [(0, 0)]
    for t0, t1 in spans:
        pts += press(t0, t1, bounce)[1:]
    return pts


@dataclass
class Scenario:
    name: str
    title: str
    tstop: float
    btn: list = field(default_factory=lambda: [(0, 0)])
    bsw: list = field(default_factory=lambda: [(0, 0)])      # SW1 (as-built only)
    vbus: list = field(default_factory=lambda: [(0, 0)])     # plug 0/1
    fwreq: list = field(default_factory=lambda: [(0, 1)])    # firmware wants PWR_HOLD
    cell: str = "3.7"                                         # volts, or "open"
    variants: tuple = ("board",)
    checks: list = field(default_factory=list)
    tstep: float = 20e-6
    tmax: float = None                                        # max step (default tstep)
    corners: tuple = None                                     # None = every corner
    extra: list = field(default_factory=list)                 # extra netlist lines
    ic: str = ""                                              # extra .ic terms
    ov: dict = field(default_factory=dict)                    # corner -> param overrides


# check helpers: each takes (wave, ctx) and returns (ok, detail)
def at(w, name, t):
    return float(np.interp(t, w["time"], w[name]))


def chk_off_at(t, label=None):
    def f(w, ctx):
        v = at(w, "3V3", t)
        return v < 0.3, f"3V3 = {v:.2f} V at {t:g}s ({label or 'expect off'})"
    f.__name__ = f"off@{t:g}s"
    return f


def chk_on_at(t, label=None):
    def f(w, ctx):
        v, lim = at(w, "3V3", t), min(3.1, at(w, "VSYS", t) - 0.35)  # LDO dropout on a low cell
        return v > lim, f"3V3 = {v:.2f} V at {t:g}s, need > {lim:.2f} ({label or 'expect on'})"
    f.__name__ = f"on@{t:g}s"
    return f


def chk_mode_at(t, want):
    """want: 'normal' (firmware running) | 'bootsel' | 'off'."""
    def f(w, ctx):
        bs, fw, v = at(w, "bsel", t), at(w, "fwon", t), at(w, "3V3", t)
        got = "off" if v < 1.6 else "bootsel" if bs > 0.5 else "normal" if fw > 0.5 else "reset"
        return got == want, f"mode at {t:g}s = {got} (want {want})"
    f.__name__ = f"mode@{t:g}s={want}"
    return f


def chk_samples(want):
    """Every bootrom sample of CSn must be a VALID level: <=0.8V for a
    BOOTSEL request, >=2.0V otherwise (scaled to IOVDD at that instant)."""
    def f(w, ctx):
        t, s = w["time"], w["smp"]
        edges = np.where((s[1:] > 0.5) & (s[:-1] <= 0.5))[0]
        if len(edges) == 0:
            return want == "none", "no bootrom sample (chip never left reset)"
        out, ok, todo = [], True, list(want) if isinstance(want, list) else None
        for i in edges:
            ts = t[i + 1]
            vcs, vdd = at(w, "BOOTSEL", ts), at(w, "3V3", ts)
            vil, vih = 0.8 * vdd / 3.3, 2.0 * vdd / 3.3
            lvl = "LOW" if vcs <= vil else "HIGH" if vcs >= vih else "INVALID"
            exp = want if todo is None else todo.pop(0) if todo else "?"
            good = (lvl == "LOW") if exp == "low" else (lvl == "HIGH")
            ok &= good
            out.append(f"t={ts*1e3:.1f}ms CSn={vcs:.2f}V ({lvl}, IOVDD {vdd:.2f})")
        return ok, "; ".join(out)
    f.__name__ = f"samples={want}"
    return f


def chk_max(name, limit, t0=0, t1=None, label=""):
    def f(w, ctx):
        t = w["time"]
        m = (t >= t0) & (t <= (t1 if t1 is not None else t[-1]))
        v = float(np.max(w[name][m]))
        return v <= limit, f"max {name} = {v:.3f} V (limit {limit}) {label}"
    f.__name__ = f"max({name})"
    return f


def chk_min(name, limit, t0=0, t1=None, label=""):
    def f(w, ctx):
        t = w["time"]
        m = (t >= t0) & (t <= (t1 if t1 is not None else t[-1]))
        v = float(np.min(w[name][m]))
        return v >= limit, f"min {name} = {v:.3f} V (limit {limit}) {label}"
    f.__name__ = f"min({name})"
    return f


def chk_vgs_q4_off(t0, t1, margin=0.10):
    """Off-state: Q4's |VGS| must stay below the hot-corner threshold
    minus a margin, i.e. LATCH_G within (|vto_p| - margin) of VBATT."""
    def f(w, ctx):
        t = w["time"]
        m = (t >= t0) & (t <= t1)
        vgs = float(np.min(w["LATCH_G"][m] - w["VBATT"][m]))
        vth = ctx["vto_p"] if ctx.get("q4_cj2101") else ctx["vto_p4"]
        lim = -(abs(vth) - margin)
        return vgs > lim, f"min VGS(Q4) = {vgs*1e3:.0f} mV (must stay above {lim*1e3:.0f} mV)"
    f.__name__ = "Q4 off margin"
    return f


def chk_fire_window(t_press, lo, hi):
    """one-button: the RUN kick must land between lo and hi seconds into the hold."""
    def f(w, ctx):
        t, run = w["time"], w["RUN"]
        m = (t > t_press + 0.05) & (run < 0.8) & (w["3V3"] > 3.0)
        if not m.any():
            return False, "RUN never pulled low (timer never fired)"
        tf = float(t[m][0]) - t_press
        ctx["fire_s"] = tf
        return lo <= tf <= hi, f"BOOTSEL fired {tf:.2f}s into the hold (window {lo}-{hi}s)"
    f.__name__ = "fire window"
    return f


def chk_clean(t):
    def f(w, ctx):
        v, hi = at(w, "3V3", t), min(3.1, at(w, "VSYS", t) - 0.35)
        state = "off" if v < 0.3 else "on" if v > hi else "HALF-ON"
        ctx["end_state"] = state
        return state != "HALF-ON", f"3V3 = {v:.2f} V at {t:g}s -> {state}"
    f.__name__ = "clean end state"
    return f


def chk_stretch(t_press):
    """Measurement, always passes: how long Q4 conducts after the contact
    opens (C27 recharging through R24 holds LATCH_G low)."""
    def f(w, ctx):
        t = w["time"]
        m = (t > t_press) & (w["LATCH_G"] - w["VBATT"] < -0.5)
        dur = float(t[m][-1] - t_press) if m.any() else 0.0
        return True, f"Q4 held on for {dur*1e3:.1f} ms from the start of a 5 ms tap"
    f.__name__ = "pulse stretch (info)"
    return f


def chk_no_fire(name="RUN"):
    def f(w, ctx):
        t = w["time"]
        m = (w["3V3"] > 3.0) & (w[name] < 0.8) & (t > 0.01)
        return not m.any(), "RUN stayed high while powered" if not m.any() else \
            f"RUN pulled low at {t[m][0]:.3f}s"
    f.__name__ = "no RUN kick"
    return f


def chk_peak_abs_diff(a, b, r_ohm, limit_a, label):
    """Peak |I| through a resistor between nodes a and b."""
    def f(w, ctx):
        m = w["time"] >= 10e-6
        i = float(np.max(np.abs(w[a][m] - w[b][m]))) / r_ohm
        return i <= limit_a, f"peak |I| {label} = {i*1e3:.1f} mA (limit {limit_a*1e3:g} mA)"
    f.__name__ = f"peak I {label}"
    return f


def chk_band(name, ref, lo, hi, label, t0=10e-6):
    """name - ref must stay within [lo, hi] V from t0 on (the first uic
    timepoint is not a physical state)."""
    def f(w, ctx):
        m = w["time"] >= t0
        d = (w[name] - (w[ref] if ref else 0))[m]
        mn, mx = float(np.min(d)), float(np.max(d))
        return lo <= mn and mx <= hi, f"{label}: {mn:.2f} .. {mx:.2f} V (allowed {lo} .. {hi})"
    f.__name__ = label
    return f


def esd(kv):
    """IEC 61000-4-2 contact-discharge network (150pF / 330R) into the
    button pad, closing at 20us. No discharge-tip inductance: that only
    makes the edge faster than the real gun, i.e. pessimistic."""
    return [f"Cesd esdq 0 150p", "Resd esdq esdr 330",
            "Vesdsw esdsw 0 PWL(0 0 20u 0 20.001u 1)",
            "Besd esdr BTN_EXT I = V(esdr,BTN_EXT) * (1e-12 + 1e3 * V(esdsw))"], \
        f" v(esdq)={kv * 1e3:g}"


S = []
# --- latch behaviour (both variants) ---
# --- latch behaviour ---
S.append(Scenario("idle_off", "Battery only, nobody touches it: stays off (leakage corner)",
                  0.5, checks=[chk_off_at(0.49), chk_vgs_q4_off(0.05, 0.5)]))
S.append(Scenario("power_on", "Press 300ms on battery: firmware latches, stays on after release",
                  0.8, btn=press(0.05, 0.35),
                  checks=[chk_samples("high"), chk_mode_at(0.3, "normal"),
                          chk_on_at(0.75, "latched after release")]))
S.append(Scenario("tap_short", "5ms tap: ends cleanly OFF or cleanly latched ON, never half-on",
                  0.4, btn=press(0.05, 0.055, bounce=False),
                  checks=[chk_clean(0.35), chk_stretch(0.05)]))
S.append(Scenario("fw_off", "Running; firmware drops PWR_HOLD at a 1.0s hold; off on release",
                  2.0, btn=presses([(0.05, 0.25), (0.6, 1.8)]),
                  fwreq=[(0, 1), (1.6, 1), (1.6001, 0)],
                  checks=[chk_on_at(1.7, "held: button keeps it up"), chk_off_at(1.95),
                          chk_no_fire()],
                  tstep=50e-6))
S.append(Scenario("usb_plug", "USB plugged in, no press: normal boot (cell 3.7V)",
                  0.3, vbus=[(0, 0), (0.05, 0), (0.0505, 1)],
                  checks=[chk_samples("high"), chk_mode_at(0.25, "normal"), chk_no_fire()]))
S.append(Scenario("usb_plug_dead", "USB plugged in, cell open (PCM tripped): normal boot",
                  0.3, vbus=[(0, 0), (0.05, 0), (0.0505, 1)], cell="open",
                  checks=[chk_samples("high"), chk_mode_at(0.25, "normal"), chk_no_fire()]))
S.append(Scenario("usb_clicks", "USB in, running: 8 quick clicks never trip BOOTSEL",
                  4.5, vbus=[(0, 0), (0.02, 0), (0.0205, 1)],
                  btn=presses([(0.3 + 0.5 * k, 0.5 + 0.5 * k) for k in range(8)]),
                  checks=[chk_mode_at(4.4, "normal"), chk_no_fire()], tstep=100e-6))
# --- BOOTSEL entry / force-off ---
S.append(Scenario("bootsel_usb", "USB in, running: hold the button 12s -> BOOTSEL, stays in it",
                  13.0, vbus=[(0, 0), (0.02, 0), (0.0205, 1)], btn=press(0.3, 12.3),
                  checks=[chk_fire_window(0.3, 2.0, 11.0), chk_samples(["high", "low"]),
                          chk_mode_at(12.9, "bootsel"), chk_on_at(12.9, "USB holds power")],
                  tstep=100e-6))
S.append(Scenario("force_off_hung", "Battery, firmware HUNG with PWR_HOLD high: hold 12s -> off on release",
                  13.0, btn=presses([(0.05, 0.3), (0.6, 12.6)]), fwreq=[(0, 1)],
                  checks=[chk_fire_window(0.6, 2.0, 11.0), chk_on_at(12.5, "held"),
                          chk_off_at(12.95, "released after reset")],
                  tstep=100e-6))
# --- review F3/F4/F8 (adoption review): limits, not typicals ---
# U8 input leakage at the Nexperia II spec max (+-1uA): the hold window
# stretches to ~18s cold (sinking) and shortens hot (sourcing).
S.append(Scenario("bootsel_ii_limit", "U8 input leakage at its +-1uA spec max: still fires, window widens",
                  23.0, vbus=[(0, 0), (0.02, 0), (0.0205, 1)], btn=press(0.3, 22.3),
                  corners=("cold", "hot"), ov={"cold": dict(ii=-1e-6), "hot": dict(ii=1e-6)},
                  checks=[chk_fire_window(0.3, 1.5, 20.0), chk_mode_at(22.9, "bootsel")],
                  tstep=200e-6))
# Firmware that forgot GPIO21's pull-up is now wrong (active high), but it
# must not walk the timer into a reset by itself: strongest pull-up (32k)
# plus U8 sourcing its spec-max 1uA, button never touched.
S.append(Scenario("pullup_left_on", "Firmware leaves GPIO21's pull-up on, U8 leaks +1uA: no spurious BOOTSEL",
                  20.0, vbus=[(0, 0), (0.02, 0), (0.0205, 1)],
                  extra=["Rpu21 3V3 BTN_SENSE 32k  $ RP2350 RPU min (Table 1683)"],
                  corners=("typ", "hot"), ov={"typ": dict(ii=1e-6), "hot": dict(ii=1e-6)},
                  checks=[chk_no_fire(), chk_mode_at(19.9, "normal")], tstep=200e-6))
# A click, then an immediate hold: D5 empties C75 only to one diode drop,
# so the next hold starts part-charged. Sets the firmware long-press bound.
S.append(Scenario("click_then_hold", "Quick click then an immediate hold: earliest possible fire",
                  13.0, vbus=[(0, 0), (0.02, 0), (0.0205, 1)],
                  btn=presses([(0.3, 0.5), (0.6, 12.6)]),
                  checks=[chk_fire_window(0.6, 1.5, 11.0)], tstep=100e-6))
# --- ESD into the button pad (gate-8 S4), board off on the cell ---
for kv in (-8, 8):
    lines, ic = esd(kv)
    S.append(Scenario(f"esd_{'neg' if kv < 0 else 'pos'}8kv",
                      f"{kv:+d} kV contact discharge into the button pad, board off: "
                      "D6 takes it, D4/C27 barely notice, board stays off",
                      0.3, extra=lines, ic=ic, tstep=1e-9, tmax=20e-6, corners=("typ", "hot"),
                      checks=[chk_band("BTN_EXT", None, -30, 30, "TVS clamp (info: rated 30kV contact)"),
                              chk_band("BTN_N", "VBATT", -0.6, 0.1, "BTN_N behind R30"),
                              chk_peak_abs_diff("BTN_EXT", "BTN_N", 1e3, 0.1, "through R30"),
                              chk_band("LATCH_G", "VBATT", -0.25, 0.8, "Q4 VGS"),
                              chk_off_at(0.29, "the strike is not a press")]))
# --- references: the committed design before 2026-10-24 (afabd86) ---
S.append(Scenario("bootsel_usb_sw1", "afabd86: hold SW1, plug USB -> BOOTSEL (reference)",
                  0.4, vbus=[(0, 0), (0.1, 0), (0.1005, 1)], bsw=press(0.05, 0.35),
                  variants=("afabd86",), corners=("typ", "cold"),
                  checks=[chk_samples("low"), chk_mode_at(0.3, "bootsel")]))
S.append(Scenario("hung_afabd86", "afabd86, firmware HUNG with PWR_HOLD high: button can't turn it off",
                  3.0, btn=presses([(0.05, 0.3), (0.6, 2.6)]), fwreq=[(0, 1)],
                  variants=("afabd86",), corners=("typ",),
                  checks=[chk_on_at(2.95, "documents the gate-2 M2 hazard: still on")],
                  tstep=100e-6))
S.append(Scenario("selfstart_afabd86", "afabd86 at 85C, nobody touches it: turns ITSELF on (the S1 defect)",
                  0.5, variants=("afabd86",), corners=("hot",),
                  checks=[chk_on_at(0.49, "documents the gate-8 S1 defect: self-started")]))

# ---------------------------------------------------------------- corners

TYP = dict(vto_p=-0.7, vto_p4=-1.4, idss=1e-9, vto_n=1.3, vt_pos=1.75, vt_neg=0.95, en_th=0.9, en_hy=0.1,
           en_pu=0.3e-6, t_samp=1e-3, t_fw=20e-3, rpu=50e3, rpd=60e3, ctmr=0.9, temp=25,
           ii=0, itvs=5e-9)
# ctmr scales C75 (CL10A106KP8NNNC, 10uF X5R 0603): +-10% tolerance, X5R
# +-15% over temperature, and DC-bias loss at the 1.4-2.4V it charges to.
# typ 0.9 = ~-10% bias at ~1.9V. hot 0.70 = 0.9 x 0.85 x 0.92 (every loss
# at once: earliest fire). cold 1.10 = +10% and NO bias credit (latest fire).
# itvs = D6 PESD5V0S1BL IRM at 25C, 5nA typ (ds); models.lib scales it with
# temperature (Fig. 6), so the hot corner's 100nA max is ~1.15uA at 85C.
CORNERS = {
    "typ": {},
    # cold: high thresholds, slow boot, timer cap +10%: latest fire, hardest to latch
    "cold": dict(vt_pos=2.2, vt_neg=1.5, ctmr=1.1, vto_p=-1.0, vto_p4=-2.1, idss=1e-10,
                 vto_n=1.5, en_th=1.05,
                 en_hy=0.2, t_samp=10e-3, t_fw=50e-3, rpu=86e3, rpd=113e3, temp=-20,
                 ii=-0.1e-6, itvs=1e-9),  # U8 input SINKS: slows the timer
    # hot: low thresholds (CJ2101 -0.45V min less ~2mV/C), fast boot, timer cap
    # -10% and -10% DC bias: earliest fire, worst leakage, most false-trigger prone
    "hot": dict(vt_pos=1.3, vt_neg=0.6, ctmr=0.70, vto_p=-0.33, vto_p4=-0.68, idss=62e-9,
                vto_n=0.8, en_th=0.7,
                en_hy=0.01, en_pu=1e-6, t_samp=50e-6, t_fw=5e-3, rpu=32e3, rpd=36e3,
                temp=85, ii=0.3e-6, itvs=100e-9),  # U8 input SOURCES: speeds the timer
}
CELLS = {"3.7": 3.7}  # per-scenario overrides below
CELL_SWEEP = {"idle_off": ["3.0", "4.2"], "power_on": ["3.0", "4.2"]}


def tb(scn, variant, corner, cellv, override=None):
    p = {**TYP, **CORNERS.get(corner, {}), **(override or {})}
    if variant == "afabd86":
        p["q4_cj2101"] = 1
    board, c = board_netlist(variant)
    cell = ("Rcell plus minus 10Meg  $ PCM open: no cell" if cellv == "open" else
            f"Vcell cp minus {cellv}\nRcell cp plus 0.15  $ LPR302823 IR")
    if "C75" in c.components:  # timer cap tolerance + DC-bias corner
        board = re.sub(r"^CC75 (\S+) (\S+) (\S+)", lambda m: f"CC75 {m.group(1)} {m.group(2)} "
                       f"{float(m.group(3)) * p['ctmr']:.4g}", board, flags=re.M)
    lines = [
        f"* {scn.name} / {variant} / {corner} / cell {cellv}",
        ".param " + " ".join(f"{k}={v:g}" for k, v in p.items()
                             if k not in ("ctmr", "temp", "tag", "q4_cj2101")),
        f".include {HERE / 'models.lib'}",
        f".include {HERE / 'mcu.lib'}",
        f".options temp={p['temp']} tnom=25",
        ".subckt CELL plus minus", cell, ".ends CELL",
        board,
        # stimulus
        f"Vbtn btn 0 {pwl(scn.btn)}",
        f"Vbsw bsw 0 {pwl(scn.bsw)}",
        f"Vfw fwreq 0 {pwl(scn.fwreq)}",
        f"Vplug plug 0 {pwl(scn.vbus)}",
        "Vusb usb5 0 5.0",
        "Busb usb5 VBUS I = V(usb5,VBUS) * (1e-9 + 3.3 * min(max(V(plug), 0), 1))",
        *scn.extra,
        # (reverse leakage lives in the diode models, calibrated per part)
        # start OFF with the cell already connected (a real board sitting in a
        # drawer). Without this the DC solve is free to pick the latched-ON
        # state, which is also a valid operating point.
        # (Set with UIC: a plain .ic op still let BTN_N/C27 start at 0.4V,
        # i.e. "button already pressed".) Every cap not listed starts at 0V.
        ".ic v(3V3)=0 v(PWR_EN)=0 v(SW_ON)=0 v(PWR_HOLD)=0 v(VBUS)=0"
        + ("" if cellv == "open" else
           f" v(LATCH_G)={cellv} v(VBATT)={cellv} v(VSYS)={cellv}"
           f" v(BTN_N)={float(cellv) - 0.3:g}"
           + ("" if variant == "afabd86" else f" v(BTN_EXT)={float(cellv) - 0.3:g}"))
        + scn.ic,
    ]
    probes = ["VBATT", "VBUS", "VSYS", "3V3", "PWR_EN", "LATCH_G", "SW_ON", "BTN_N",
              "BOOTSEL", "RUN", "PWR_HOLD", "BTN_SENSE", "act", "smp", "bsel", "fwon"]
    if variant != "afabd86":
        probes += ["PRESS_N", "BOOT_TMR", "LONG", "RUN_KICK", "BTN_EXT"]
    raw = f"{scn.name}__{variant}__{corner}__{cellv}"
    if override and "tag" in override:
        raw += "__" + override["tag"]
    lines += [
        ".control",
        "set wr_singlescale", "set wr_vecnames", "option numdgt=7",
        f"tran {scn.tstep:g} {scn.tstop:g} 0 {scn.tmax or scn.tstep:g} uic",
        f"wrdata {OUT / 'data' / raw}.txt " + " ".join(f"v({x})" for x in probes),
        "quit",
        ".endc", ".end",
    ]
    return raw, "\n".join(lines), p, probes


def ngspice_bin(arg):
    for cand in (arg, os.environ.get("NGSPICE"), shutil.which("ngspice"),
                 str(Path.home() / "miniforge3/envs/spice/bin/ngspice")):
        if cand and Path(cand).exists():
            return cand
    sys.exit("ngspice not found: pass --ngspice, set $NGSPICE, or "
             "`mamba create -n spice -c conda-forge ngspice`")


def run_one(ng, scn, variant, corner, cellv):
    raw, net, p, probes = tb(scn, variant, corner, cellv, scn.ov.get(corner))
    cir = OUT / "netlists" / f"{raw}.cir"
    cir.write_text(net)
    r = subprocess.run([ng, "-b", str(cir)], capture_output=True, text=True, timeout=1800)
    log = OUT / "logs" / f"{raw}.log"
    log.write_text(r.stdout + r.stderr)
    dat = OUT / "data" / f"{raw}.txt"
    res = dict(scenario=scn.name, variant=variant, corner=corner, cell=cellv, raw=raw)
    if not dat.exists():
        res.update(ok=False, checks=[("ngspice", False, "no output; see " + log.name)])
        return res
    arr = np.loadtxt(dat, skiprows=1)
    hdr = dat.read_text().split("\n", 1)[0].split()
    byname = {pr.upper(): pr for pr in probes}
    w = {"time": arr[:, 0]}
    for i, h in enumerate(hdr[1:], 1):
        m = re.fullmatch(r"v\((.+)\)", h)
        key = (m.group(1) if m else h).upper()
        w[byname.get(key, key)] = arr[:, i]
    ctx = dict(p)
    checks = []
    for chk in scn.checks:
        try:
            ok, detail = chk(w, ctx)
        except Exception as e:  # a check that crashes is a failed check
            ok, detail = False, f"check error: {e}"
        checks.append((chk.__name__, bool(ok), detail))
    res.update(ok=all(c[1] for c in checks), checks=checks,
               fire_s=ctx.get("fire_s"), t_end=float(w["time"][-1]))
    plot(w, scn, res, variant, probes)
    return res


def plot(w, scn, res, variant, probes):
    from matplotlib.figure import Figure  # pyplot is not thread-safe
    groups = [("rails", ["VBATT", "VBUS", "VSYS", "3V3"]),
              ("latch", ["LATCH_G", "BTN_N", "PWR_EN", "PWR_HOLD"]),
              ("boot", ["BOOTSEL", "RUN", "BTN_SENSE"] +
               (["BOOT_TMR", "LONG"] if variant != "afabd86" else [])),
              ("mcu", ["act", "smp", "bsel", "fwon"])]
    fig = Figure(figsize=(10, 8.5))
    axs = fig.subplots(len(groups), 1, sharex=True)
    t = w["time"]
    for ax, (g, names) in zip(axs, groups):
        for n in names:
            if n in w:
                ax.plot(t, w[n] + (0 if g != "mcu" else 0), label=n, lw=1.1)
        ax.set_ylabel(g)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=7, ncol=4)
    axs[-1].set_xlabel("time (s)")
    fig.suptitle(f"{scn.title}\n{variant} / {res['corner']} / cell {res['cell']} — "
                 f"{'PASS' if res['ok'] else 'FAIL'}", fontsize=10)
    fig.tight_layout()
    fig.savefig(OUT / "plots" / f"{res['raw']}.png", dpi=90)


# ------------------------------------------------- off-state EN vs temperature

TSWEEP = [25, 40, 50, 60, 70, 85]


def tsweep(ng, j):
    """Board OFF, no button, no USB: what voltage do leakage paths put on
    the LDO's EN pin? The LDO is told never to enable (en_th = 10V) so the
    leak can be measured instead of acted on. Typical parts; CJ2101 |VGS(th)|
    falls ~2mV/C. Compare against the NCP730 EN threshold, 0.7-1.05V."""
    scn = Scenario("tsweep", "off-state EN vs temperature", 0.3, tstep=100e-6)
    jobs = [(v, T) for v in SWEEP_VARIANTS for T in TSWEEP]

    def one(job):
        v, T = job
        ov = dict(temp=T, en_th=10, vto_p=-0.7 + 0.002 * (T - 25),
                  vto_p4=-1.4 + 0.002 * (T - 25), tag=f"T{T}")
        raw, net, p, probes = tb(scn, v, "typ", "3.7", ov)
        cir = OUT / "netlists" / f"{raw}.cir"
        cir.write_text(net)
        subprocess.run([ng, "-b", str(cir)], capture_output=True, text=True, timeout=600)
        dat = OUT / "data" / f"{raw}.txt"
        arr = np.loadtxt(dat, skiprows=1)
        hdr = [h[2:-1].upper() if h.startswith("v(") else h
               for h in dat.read_text().split("\n", 1)[0].split()]
        last = dict(zip(hdr, arr[-1]))
        return dict(variant=v, T=T, en=last["PWR_EN"], vbus=last["VBUS"],
                    sw_on=last["SW_ON"])
    with ThreadPoolExecutor(j) as ex:
        rows = list(ex.map(one, jobs))
    from matplotlib.figure import Figure
    fig = Figure(figsize=(8, 4.2))
    ax = fig.subplots()
    ax.axhspan(0.7, 1.05, color="tab:red", alpha=0.15, label="NCP730 EN threshold 0.7-1.05 V")
    for v in SWEEP_VARIANTS:
        r = [x for x in rows if x["variant"] == v]
        ax.plot([x["T"] for x in r], [x["en"] for x in r], "o-", label=f"EN  {v}")
        ax.plot([x["T"] for x in r], [x["vbus"] for x in r], "x--", alpha=0.6,
                label=f"VBUS {v}")
    ax.set_xlabel("temperature (°C)")
    ax.set_ylabel("V, board OFF, no USB")
    ax.set_yscale("log")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(OUT / "plots" / "tsweep.png", dpi=100)
    return rows


def report(results, sweep=None):
    rows = []
    for r in results:
        det = "<br>".join(f"{'✔' if ok else '✘'} <b>{html.escape(n)}</b>: {html.escape(d)}"
                          for n, ok, d in r["checks"])
        rows.append(f"<tr class='{'ok' if r['ok'] else 'bad'}'><td>{r['scenario']}</td>"
                    f"<td>{r['variant']}</td><td>{r['corner']}</td><td>{r['cell']}</td>"
                    f"<td>{'PASS' if r['ok'] else 'FAIL'}</td><td>{det}</td>"
                    f"<td><a href='plots/{r['raw']}.png'><img src='plots/{r['raw']}.png' "
                    f"width=220></a></td></tr>")
    titles = "".join(f"<li><b>{s.name}</b> — {html.escape(s.title)}</li>" for s in S)
    npass = sum(r["ok"] for r in results)
    sweep_html = ""
    if sweep:
        trs = "".join(f"<tr><td>{x['variant']}</td><td>{x['T']}</td><td>{x['en']:.3f}</td>"
                      f"<td>{x['vbus']:.3f}</td><td>{x['sw_on']:.3f}</td></tr>" for x in sweep)
        sweep_html = (f"<h2>Off-state EN vs temperature</h2><p>Board off, no button, no USB. "
                      f"EN at or above 0.7&nbsp;V can start the LDO (NCP730 min threshold).</p>"
                      f"<img src='plots/tsweep.png' style='max-width:800px'>"
                      f"<table style='width:auto'><tr><th>variant</th><th>°C</th><th>EN</th>"
                      f"<th>VBUS</th><th>SW_ON</th></tr>{trs}</table>")
    page = f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Button sim</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--mut:#666;--ok:#e7f6ea;--bad:#fde8e8;--line:#ddd}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16171a;--fg:#e6e6e6;--mut:#999;--ok:#173322;--bad:#3a1b1b;--line:#333}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:16px;max-width:1300px}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid var(--line);padding:6px;vertical-align:top;font-size:12px}}
tr.ok td{{background:var(--ok)}}tr.bad td{{background:var(--bad)}}img{{max-width:100%}}
.mut{{color:var(--mut)}}</style></head><body>
<h1>Power button / BOOTSEL — ngspice</h1>
<p><b>{npass}/{len(results)} runs pass.</b> Netlist pulled from <code>scripts/circuit.py</code>;
variant <i>board</i> is the circuit as it stands; <i>afabd86</i> is the pre-2026-10-24 design,
kept as a reference patch in <code>design/sim/button/run.py</code>.
Corners: typ, slow (late timer, high thresholds, slow boot), fast (early timer, low thresholds,
85&nbsp;°C leakage). Models: <code>design/sim/button/models.lib</code>, <code>mcu.lib</code>.</p>
<ul class=mut>{titles}</ul>
{sweep_html}
<table><tr><th>scenario</th><th>variant</th><th>corner</th><th>cell</th><th></th><th>checks</th><th>waveform</th></tr>
{''.join(rows)}</table></body></html>"""
    (OUT / "index.html").write_text(page)
    (OUT / "results.json").write_text(json.dumps(results, indent=1, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ngspice")
    ap.add_argument("--quick", action="store_true", help="typical corner only")
    ap.add_argument("-k", default="", help="only scenarios whose name contains this")
    ap.add_argument("-j", type=int, default=os.cpu_count())
    a = ap.parse_args()
    ng = ngspice_bin(a.ngspice)
    for d in ("netlists", "data", "logs", "plots"):
        (OUT / d).mkdir(parents=True, exist_ok=True)
    jobs = []
    for scn in S:
        if a.k not in scn.name:
            continue
        for variant in scn.variants:
            cs = list(scn.corners or CORNERS)
            for corner in ([c for c in cs if c == "typ"] if a.quick else cs):
                for cellv in ([scn.cell] + ([] if a.quick else CELL_SWEEP.get(scn.name, []))
                              if scn.cell != "open" else ["open"]):
                    jobs.append((scn, variant, corner, cellv))
    print(f"{len(jobs)} runs on {a.j} threads, ngspice = {ng}")
    with ThreadPoolExecutor(a.j) as ex:
        results = list(ex.map(lambda j: run_one(ng, *j), jobs))
    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['scenario']:16s} {r['variant']:9s} "
              f"{r['corner']:5s} cell {r['cell']}")
        for n, ok, d in r["checks"]:
            if not ok:
                print(f"        ✘ {n}: {d}")
    sweep = None if a.k or a.quick else tsweep(ng, a.j)
    if sweep:
        print("off-state EN vs temperature (V):")
        for v in SWEEP_VARIANTS:
            print(f"  {v:14s} " + "  ".join(f"{x['T']}C={x['en']:.2f}"
                                            for x in sweep if x["variant"] == v))
    report(results, sweep)
    print(f"report: {OUT / 'index.html'}")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
