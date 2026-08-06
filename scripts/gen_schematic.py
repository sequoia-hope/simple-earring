#!/usr/bin/env python3
"""Generate a readable .kicad_sch from circuit.py — documentation, not a
netlist source.

The board is generated from code, so there has never been a schematic to
read. This emits one: every component gets a box symbol whose pins carry
their real names, and connections are shown as GLOBAL NET LABELS rather
than drawn wires. That keeps the generator simple and the sheet readable
(no router, no crossing rats' nest), at the cost of looking like a
"labels everywhere" schematic — which is the normal idiom for a dense
board like this anyway.

Repetitive banks are collapsed so the sheet stays legible: the 45-LED
chain shows its first two and last two members plus a summary note, and
the 100n decoupling bank shows one representative cap per rail. The full
per-part detail lives in the board and in bom/parts.yaml.

Output: out/earring.kicad_sch (tracked in git). Regenerate with
`python3 build.py --only schematic`.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import build_circuit, load_design  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "earring.kicad_sch"

# Deterministic UUIDs: same circuit -> same file, so git diffs show real
# changes instead of a fresh set of random ids every build.
NS = uuid.UUID("6f1c9d2e-3a4b-4c5d-8e9f-0a1b2c3d4e5f")
SHEET_UUID = uuid.uuid5(NS, "sheet")

FP_LIB = "earring"     # fp-lib-table nickname; gen_board.py writes the
                       # table and stamps the same nickname on the board
GRID = 2.54            # KiCad's 100mil pin pitch; everything snaps to it
FONT = "(effects (font (size 1.27 1.27))"


def uid(*parts):
    return str(uuid.uuid5(NS, "/".join(str(p) for p in parts)))


def snap(v):
    return round(round(v / GRID) * GRID, 4)


# --- sheet layout ------------------------------------------------------
# Reading order of the functional blocks. Positions are NOT hand-placed:
# main() measures each symbol and flows the sections down columns, because
# pin counts change whenever the netlist does (the QSPI swap alone moved
# every box below the MCU).
SECTIONS = [
    ("MCU", ["U1"]),
    ("QSPI flash + BOOTSEL", ["U7", "C25", "R3", "SW1"]),
    ("Crystal", ["Y1", "R1", "C14", "C15"]),
    ("USB-C + ESD + series R", ["J1", "U5", "R6", "R7", "R4", "R5"]),
    ("Charger + battery", ["U2", "R8", "C16", "C17", "BT1",
                           "R11", "R12", "C21"]),
    ("3V3 LDO + power switch", ["U3", "C18", "C19", "C9", "SW2", "R2"]),
    ("VLED load switch", ["U4", "C20", "R10"]),
    ("RP2350 core regulator", ["L1", "C11", "C12", "C13", "R13", "C22"]),
    ("IMU (I2C1)", ["U6", "C23", "C24", "R14", "R15"]),
    ("Debug / test points", ["TP1", "TP2", "TP3"]),
]

PAPER = "A1"           # 841 x 594 mm landscape — the full 45-LED chain
PAGE_W, PAGE_H = 841.0, 594.0
MARGIN_TOP = 42.0      # below the title block text
MARGIN_BOT = 250.0     # bottom band reserved for the repetitive banks
COL_W = 92.0           # column pitch: widest box + its labels either side
COL_X0 = 42.0

# Repetitive banks (LED chain, bypass caps) are drawn in FULL as grids:
# the sheet drives the PCB, and KiCad deletes board footprints that have
# no symbol. Grid pitch fits a 4-pin box plus a net label either side.
BANK_Y = PAGE_H - MARGIN_BOT + 10
BANK_COLS = 16
BANK_PITCH_X = 48.0


def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def summarize(refs):
    """C30, C32, C34... -> 'C30..C74 (23)'. Listing every collapsed ref
    is noise; the reader wants to know which families were left out."""
    from collections import defaultdict
    fam = defaultdict(list)
    for r in refs:
        i = 0
        while i < len(r) and not r[i].isdigit():
            i += 1
        fam[r[:i]].append(int(r[i:]) if r[i:].isdigit() else 0)
    out = []
    for prefix, nums in sorted(fam.items()):
        nums.sort()
        out.append(f"{prefix}{nums[0]}..{prefix}{nums[-1]} ({len(nums)})"
                   if len(nums) > 2 else
                   ", ".join(f"{prefix}{n}" for n in nums))
    return "; ".join(out)


class Sch:
    """Accumulates lib_symbols, symbol instances, labels and text."""

    def __init__(self):
        self.lib = {}       # name -> s-expr string
        self.geom = {}      # name -> (rows, half_w, top)
        self.body = []

    # -- symbol definition -------------------------------------------
    def define(self, name, pins, value, wide=False):
        """pins: list of (number, pinname, side) with side in 'lr'."""
        if name in self.lib:
            return self.geom[name]
        left = [p for p in pins if p[2] == "l"]
        right = [p for p in pins if p[2] == "r"]
        rows = max(len(left), len(right), 1)
        half_w = 12.7 if wide else 8.89
        top = (rows - 1) * GRID / 2 + GRID
        bot = -top
        out = [f'\t\t(symbol "gen:{esc(name)}"',
               '\t\t\t(pin_numbers (hide no))',
               '\t\t\t(pin_names (offset 0.508))',
               '\t\t\t(exclude_from_sim no)',
               '\t\t\t(in_bom yes)',
               '\t\t\t(on_board yes)',
               f'\t\t\t(property "Reference" "U" (at 0 {top + 2.54:.2f} 0)',
               f'\t\t\t\t{FONT}))',
               f'\t\t\t(property "Value" "{esc(value)}" '
               f'(at 0 {bot - 2.54:.2f} 0)',
               f'\t\t\t\t{FONT}))',
               '\t\t\t(property "Footprint" "" (at 0 0 0)',
               '\t\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))',
               f'\t\t\t(symbol "{esc(name)}_0_1"',
               f'\t\t\t\t(rectangle (start {-half_w:.2f} {top:.2f}) '
               f'(end {half_w:.2f} {bot:.2f})',
               '\t\t\t\t\t(stroke (width 0.254) (type default))',
               '\t\t\t\t\t(fill (type background))))',
               f'\t\t\t(symbol "{esc(name)}_1_1"']
        for side, group in (("l", left), ("r", right)):
            for i, (num, pname, _) in enumerate(group):
                y = top - GRID - i * GRID
                if side == "l":
                    x, rot = -half_w - 2.54, 0
                else:
                    x, rot = half_w + 2.54, 180
                out.append(
                    f'\t\t\t\t(pin passive line (at {x:.2f} {y:.2f} {rot}) '
                    f'(length 2.54)')
                out.append(f'\t\t\t\t\t(name "{esc(pname)}" {FONT}))')
                out.append(f'\t\t\t\t\t(number "{esc(num)}" {FONT})))')
        out.append('\t\t\t))')
        self.lib[name] = "\n".join(out)
        self.geom[name] = (rows, half_w, top)
        return self.geom[name]

    # -- placed instance ---------------------------------------------
    def place(self, symname, ref, value, x, y, pins, wide=False,
              footprint=""):
        """pins: list of (number, pinname, side, netname)."""
        defpins = [(n, pn, s) for n, pn, s, _ in pins]
        rows, half_w, top = self.define(symname, defpins, value, wide)
        x, y = snap(x), snap(y)
        self.body.append(
            f'\t(symbol\n\t\t(lib_id "gen:{esc(symname)}")\n'
            f'\t\t(at {x:.2f} {y:.2f} 0)\n\t\t(unit 1)\n'
            f'\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n'
            f'\t\t(on_board yes)\n\t\t(dnp no)\n'
            f'\t\t(uuid "{uid("sym", ref)}")\n'
            f'\t\t(property "Reference" "{esc(ref)}" '
            f'(at {x:.2f} {y - top - 2.54:.2f} 0)\n\t\t\t{FONT}))\n'
            f'\t\t(property "Value" "{esc(value)}" '
            f'(at {x:.2f} {y + top + 2.54:.2f} 0)\n\t\t\t{FONT}))\n'
            # Footprint is what lets "Update PCB from Schematic" bind a
            # symbol to a board footprint; without it KiCad reports
            # "Cannot update <ref> (no footprint assigned)".
            f'\t\t(property "Footprint" "{FP_LIB}:{esc(footprint)}" '
            f'(at {x:.2f} {y:.2f} 0)\n'
            f'\t\t\t(effects (font (size 1.27 1.27)) (hide yes)))\n'
            + "".join(f'\t\t(pin "{esc(n)}" (uuid "{uid("pin", ref, n)}"))\n'
                      for n, _, _, _ in pins)
            + f'\t\t(instances\n\t\t\t(project "earring"\n'
            f'\t\t\t\t(path "/{SHEET_UUID}"\n'
            f'\t\t\t\t\t(reference "{esc(ref)}") (unit 1)))))')
        # a global label at each connected pin's far end
        left = [p for p in pins if p[2] == "l"]
        right = [p for p in pins if p[2] == "r"]
        for side, group in (("l", left), ("r", right)):
            for i, (num, _, _, net) in enumerate(group):
                py = y - (top - GRID - i * GRID)
                if side == "l":
                    px, rot, just = x - half_w - 2.54, 180, "right"
                else:
                    px, rot, just = x + half_w + 2.54, 0, "left"
                if net:
                    self.label(net, px, py, rot, just, uid("lbl", ref, num))
                else:
                    # Unused pin: flag it no-connect rather than leaving it
                    # dangling. Otherwise the netlist invents a single-pin
                    # net per pad (U1 alone has 22 unused GPIOs) and ERC
                    # reports every one of them.
                    self.body.append(
                        f'\t(no_connect (at {px:.2f} {py:.2f})\n'
                        f'\t\t(uuid "{uid("nc", ref, num)}"))')

    def label(self, net, x, y, rot, just, u):
        self.body.append(
            f'\t(global_label "{esc(net)}" (shape input) '
            f'(at {x:.2f} {y:.2f} {rot})\n'
            f'\t\t{FONT} (justify {just}))\n\t\t(uuid "{u}"))')

    def wrapped(self, s, x, y, width_mm, size=1.4):
        """Emit s as several lines that fit width_mm. KiCad has no text
        box, and an unwrapped note runs straight off the sheet edge and
        under the title block."""
        per_char = size          # conservative: KiCad's stroke font runs
                                 # ~0.8*size per char, and a note that
                                 # overruns lands under the title block
        cols = max(20, int(width_mm / per_char))
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
            self.text(ln, x, y + i * (size * 1.9), size=size)
        return len(lines)

    def text(self, s, x, y, size=1.27, bold=False):
        b = " (bold yes)" if bold else ""
        self.body.append(
            f'\t(text "{esc(s)}" (at {snap(x):.2f} {snap(y):.2f} 0)\n'
            f'\t\t(effects (font (size {size} {size}){b}) '
            f'(justify left bottom))\n'
            f'\t\t(uuid "{uid("txt", x, y, s[:24])}"))')

    def render(self, paper=None):
        return ("(kicad_sch\n"
                "\t(version 20250114)\n"
                '\t(generator "gen_schematic")\n'
                '\t(generator_version "9.0")\n'
                f'\t(uuid "{SHEET_UUID}")\n'
                f'\t(paper "{paper or PAPER}")\n'
                "\t(lib_symbols\n"
                + "\n".join(self.lib.values())
                + "\n\t)\n"
                + "\n".join(self.body)
                + "\n)\n")


def pin_sides(comp, pins):
    """Split a component's pins into left (inputs/power-in) and right.

    Heuristic: power and ground on the left, everything else balanced.
    For 2-pin parts pin 1 goes left, pin 2 right, which reads naturally
    for series elements.
    """
    items = sorted(pins.items(), key=lambda kv: int(kv[0])
                   if kv[0].isdigit() else 999)
    if len(items) <= 2:
        return [(n, _pin_name(comp, n), "l" if i == 0 else "r", net)
                for i, (n, net) in enumerate(items)]
    half = (len(items) + 1) // 2
    out = []
    for i, (n, net) in enumerate(items):
        out.append((n, _pin_name(comp, n), "l" if i < half else "r", net))
    return out


# Pin names worth spelling out. Anything not listed falls back to the pad
# number, which is what a passive's pins are called anyway.
PIN_NAMES = {
    "mcu": {},          # filled from circuit.RP_PINS below
    "flash": {"1": "/CS", "2": "DO/IO1", "3": "/WP/IO2", "4": "GND",
              "5": "DI/IO0", "6": "CLK", "7": "/HOLD/IO3", "8": "VCC",
              "9": "EP"},
    "led": {"1": "GND", "2": "DIN", "3": "VDD", "4": "DOUT"},
    "imu": {"1": "SDO/SA0", "2": "SDx", "3": "SCx", "4": "CS", "5": "VDDIO",
            "9": "GND", "10": "GND", "11": "INT1", "12": "INT2",
            "13": "SCL", "14": "SDA", "8": "VDD"},
    "charger": {"1": "TEMP", "2": "PROG", "3": "GND", "4": "VCC", "5": "BAT",
                "6": "DONE", "7": "CHRG", "8": "CE", "9": "EP"},
    "ldo": {"1": "IN", "2": "GND", "3": "EN", "4": "NC", "5": "OUT",
            "6": "BYP", "7": "EP"},
    "load_switch": {"A1": "VIN", "B1": "GND", "A2": "ON", "B2": "VOUT"},
    "usb_esd": {"1": "IO1", "2": "GND", "3": "IO2", "4": "IO2", "5": "VBUS",
                "6": "IO1"},
}


def _mcu_pin_names():
    from circuit import GPIO, RP_PINS
    names = {}
    for key, val in RP_PINS.items():
        for p in (val if isinstance(val, list) else [val]):
            names[str(p)] = key
    for gp, pin in GPIO.items():
        names.setdefault(str(pin), f"GPIO{gp}")
    names["61"] = "GND (EP)"
    return names


def _pin_name(comp, num):
    if comp.part == "mcu":
        return _mcu_pin_names().get(num, num)
    return PIN_NAMES.get(comp.part, {}).get(num, num)


def main():
    design = load_design()
    cir = build_circuit(design)
    comps = cir.components
    sch = Sch()

    n_leds = design["leds"]["count"]
    led_refs = [f"LED{i+1}" for i in range(n_leds)]
    # bypass caps that ride the LED ring (C30+)
    ring_caps = [r for r in comps
                 if r.startswith("C") and r[1:].isdigit()
                 and int(r[1:]) >= 30]

    sch.text("simple_earring — generated schematic "
             "(regenerate: python3 build.py --only schematic)",
             20, 20, size=3.0, bold=True)
    sch.text("Connections are shown as GLOBAL NET LABELS, not wires — "
             "same-named labels are the same net. Every component is "
             "drawn, so this sheet can drive the PCB. "
             "Generated from scripts/circuit.py; do not hand-edit.",
             20, 27, size=1.8)
    sch.text(f"{len(comps)} components / {len(cir.nets)} nets / "
             f"{design['board']['layers']}-layer stackup / "
             f"MCU RP2350A + W25Q16JV QSPI flash / "
             f"{n_leds} x SK6805-EC10", 20, 33, size=1.8)

    # Flow the sections down columns, measuring as we go so a netlist
    # change can never silently overlap two boxes.
    col, cursor = 0, MARGIN_TOP
    for title, refs in SECTIONS:
        members = [(r, comps[r]) for r in refs if r in comps]
        if not members:
            continue
        heights = []
        for ref, comp in members:
            pins = pin_sides(comp, comp.pins)
            rows = max(sum(1 for p in pins if p[2] == "l"),
                       sum(1 for p in pins if p[2] == "r"), 1)
            heights.append((rows + 1) * GRID + 7.62)   # box + ref/value text
        need = sum(heights) + 12.0                     # + section heading
        if cursor + need > PAGE_H - MARGIN_BOT and cursor > MARGIN_TOP:
            col += 1
            cursor = MARGIN_TOP
        sx = COL_X0 + col * COL_W
        sch.text(title, sx - 26, cursor, size=2.2, bold=True)
        cursor += 10.0
        for (ref, comp), h in zip(members, heights):
            pins = pin_sides(comp, comp.pins)
            _, _, top = sch.define(
                comp.part, [(n, pn, s) for n, pn, s, _ in pins],
                comp.value, comp.part == "mcu")
            sch.place(comp.part, ref, comp.value, sx, cursor + top + 2.54,
                      pins, wide=comp.part == "mcu",
                      footprint=comp.footprint)
            cursor += h
        cursor += 8.0

    # ---- repetitive banks: drawn in FULL, laid out as grids ----
    # These were collapsed to a representative + a note when the sheet was
    # documentation-only. It has to drive the PCB ("Update PCB from
    # Schematic"), and KiCad offers to DELETE any board footprint with no
    # matching symbol — so every component gets drawn, banks included.
    placed = {r for _, refs in SECTIONS for r in refs} & set(comps)
    banks = [
        ("LED ring — SK6805-EC10 chain (DOUT n -> DIN n+1 = LED_D<n>; "
         "head LED_D0 from U1; VDD = VLED)", led_refs),
        ("LED ring bypass caps — one per 2 LEDs, VLED-GND", ring_caps),
        ("MCU decoupling — 3V3-GND, one per IOVDD/OTP_VDD/QSPI_IOVDD/"
         "ADC_AVDD pin", [r for r in comps if r.startswith("C")
                          and r[1:].isdigit() and int(r[1:]) <= 10]),
    ]
    gy = BANK_Y
    for title, refs in banks:
        refs = [r for r in refs if r in comps and r not in placed]
        if not refs:
            continue
        sch.text(f"{title}  [{len(refs)}]", COL_X0 - 20, gy, size=2.0,
                 bold=True)
        gy += 9.0
        rowh = 0.0
        for i, ref in enumerate(refs):
            comp = comps[ref]
            pins = pin_sides(comp, comp.pins)
            _, _, top = sch.define(
                comp.part, [(n, pn, s) for n, pn, s, _ in pins],
                comp.value, False)
            cx = i % BANK_COLS
            cy = i // BANK_COLS
            rowh = (top * 2) + 10.16
            sch.place(comp.part, ref, comp.value,
                      COL_X0 + cx * BANK_PITCH_X,
                      gy + top + 2.54 + cy * rowh,
                      pins, footprint=comp.footprint)
            placed.add(ref)
        gy += ((len(refs) - 1) // BANK_COLS + 1) * rowh + 10.0

    missing = sorted(r for r in comps if r not in placed)
    assert not missing, ("every component must be drawn or the PCB link "
                         f"breaks; missing: {missing}")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(sch.render())
    print(f"wrote {OUT}: {len(sch.lib)} symbols, "
          f"{len(comps)} components, {len(cir.nets)} nets")
    # Register the root sheet in the project file, else KiCad opens the
    # project with an empty sheet list and "Update PCB from Schematic"
    # has nothing to read.
    pro = OUT.parent / "earring.kicad_pro"
    if pro.exists():
        import json
        d = json.loads(pro.read_text())
        want = [[str(SHEET_UUID), ""]]
        if d.get("sheets") != want:
            d["sheets"] = want
            pro.write_text(json.dumps(d, indent=2))
            print(f"  registered root sheet in {pro.name}")

    # SVG + PDF beside it: the .kicad_sch needs KiCad to open, but the
    # review dashboard is a browser on :8618, so it links these.
    import subprocess
    for args, label in (
            (["--exclude-drawing-sheet", "-o", str(OUT.parent)], "svg"),
            (["-o", str(OUT.parent / "earring-schematic.pdf")], "pdf")):
        r = subprocess.run(["kicad-cli", "sch", "export", label] + args
                           + [str(OUT)], capture_output=True, text=True)
        if r.returncode:
            print(f"  WARNING: {label} export failed: {r.stderr.strip()}")


if __name__ == "__main__":
    main()
