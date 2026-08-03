#!/usr/bin/env python3
"""Circuit definition: components + nets for the simple_earring board.

This is the electrical source of truth. gen_board.py consumes build_circuit().

Pin references verified against:
  - RP2350 QFN-60 pin table (from rp2350a-compact, matches datasheet)
  - LGS4056H datasheet rev C (TEMP->GND disables NTC, I=900/R_PROG <300mA)
  - NCP730 WDFN-6, TPS22913 YZV 4-ball, USBLC6-2P6 SOT-666 (from earring)
  - TBA-C1010MB-J2I16 datasheet (1=DI, 2=VCC, 3=GND, 4=DO)
RP2354A == RP2350A pinout; QSPI pins NC (internal flash) except QSPI_SS
which stays as the BOOTSEL strap (button + 1k to GND).
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Component:
    ref: str
    part: str          # key into bom/parts.yaml
    value: str
    footprint: str = ""  # filled from parts.yaml
    lcsc: str = ""
    pins: dict = field(default_factory=dict)  # pad number -> net name


@dataclass
class Circuit:
    components: dict = field(default_factory=dict)  # ref -> Component
    design: dict = field(default_factory=dict)

    def add(self, ref, part, value, pins):
        assert ref not in self.components, f"duplicate ref {ref}"
        self.components[ref] = Component(ref, part, value, pins={str(k): v for k, v in pins.items()})
        return self.components[ref]

    @property
    def nets(self):
        nets = {}
        for c in self.components.values():
            for pad, net in c.pins.items():
                if net:
                    nets.setdefault(net, []).append((c.ref, pad))
        return nets


# RP2350A/RP2354A QFN-60: name -> pin number (multi-pins listed)
RP_PINS = {
    "IOVDD": [1, 11, 20, 30, 38, 45],
    "DVDD": [6, 23, 39],
    "XIN": 21, "XOUT": 22,
    "SWCLK": 24, "SWD": 25, "RUN": 26,
    "ADC_AVDD": 44, "VREG_AVDD": 46, "VREG_PGND": 47,
    "VREG_LX": 48, "VREG_VIN": 49, "VREG_FB": 50,
    "USB_DM": 51, "USB_DP": 52, "USB_OTP_VDD": 53,
    "QSPI_IOVDD": 54, "QSPI_SS": 60,
    "QSPI_NC": [55, 56, 57, 58, 59],
    "GND": 61,  # EP
    "GPIO29_ADC3": 43,
}
GPIO = {n: n + 2 if n <= 15 else n + 11 for n in range(0, 26)}  # GPIO0->pin2 ... GPIO15->pin17? (see note)
# NOTE: QFN-60 GPIO pins are irregular; explicit map below overrides the naive one.
GPIO = {0: 2, 1: 3, 2: 4, 3: 5, 4: 7, 5: 8, 6: 9, 7: 10, 8: 12, 9: 13,
        10: 14, 11: 15, 12: 16, 13: 17, 14: 18, 15: 19, 16: 27, 17: 28,
        18: 29, 19: 31, 20: 32, 21: 33, 22: 34, 23: 35, 24: 36, 25: 37}

# GPIO roles
GP_LED_DATA = 18  # pin 29: lands top-left after the 180deg MCU rotation,
                  # right next to LED1 at the start of the ring
GP_LED_EN = 1     # -> TPS22913 ON
ADC_VBSENSE = 43  # GPIO29_ADC3 pin number


def load_parts():
    return yaml.safe_load((ROOT / "bom" / "parts.yaml").read_text())


def load_design():
    return yaml.safe_load((ROOT / "design.yaml").read_text())


def build_circuit(design=None):
    design = design or load_design()
    parts = load_parts()
    c = Circuit(design=design)
    n_leds = design["leds"]["count"]

    # --- MCU ---
    u1 = {}
    for p in RP_PINS["IOVDD"]:
        u1[p] = "3V3"
    for p in RP_PINS["DVDD"]:
        u1[p] = "VDD_CORE"
    for p in RP_PINS["QSPI_NC"]:
        u1[p] = ""  # NC — internal flash
    u1[RP_PINS["XIN"]] = "XIN"
    u1[RP_PINS["XOUT"]] = "XOUT"
    u1[RP_PINS["SWCLK"]] = "SWCLK"
    u1[RP_PINS["SWD"]] = "SWDIO"
    u1[RP_PINS["RUN"]] = "RUN"
    u1[RP_PINS["ADC_AVDD"]] = "3V3"
    u1[RP_PINS["VREG_AVDD"]] = "3V3"
    u1[RP_PINS["VREG_PGND"]] = "GND"
    u1[RP_PINS["VREG_LX"]] = "VREG_LX"
    u1[RP_PINS["VREG_VIN"]] = "3V3"
    u1[RP_PINS["VREG_FB"]] = "VDD_CORE"
    u1[RP_PINS["USB_DM"]] = "USB_DM"
    u1[RP_PINS["USB_DP"]] = "USB_DP"
    u1[RP_PINS["USB_OTP_VDD"]] = "3V3"
    u1[RP_PINS["QSPI_IOVDD"]] = "3V3"
    u1[RP_PINS["QSPI_SS"]] = "BOOTSEL"
    u1[RP_PINS["GND"]] = "GND"
    u1[GPIO[GP_LED_DATA]] = "LED_D0"
    u1[GPIO[GP_LED_EN]] = "LED_EN"
    u1[ADC_VBSENSE] = "VBSENSE"
    for p in list(GPIO.values()) + [40, 41, 42]:  # GPIO26/27/28 = pins 40-42
        u1.setdefault(p, "")  # unused GPIOs NC
    c.add("U1", "mcu", "RP2354A", u1)

    # --- IOVDD / rail decoupling on MCU ---
    for i, _ in enumerate(RP_PINS["IOVDD"] + [53, 54, 44, 46]):
        c.add(f"C{i+1}", "c_100n", "100n", {1: "3V3", 2: "GND"})
    # VREG: 4.7u in, 2x4.7u out
    c.add("C11", "c_4u7", "4.7u", {1: "3V3", 2: "GND"})       # VREG_VIN
    c.add("C12", "c_4u7", "4.7u", {1: "VDD_CORE", 2: "GND"})
    c.add("C13", "c_4u7", "4.7u", {1: "VDD_CORE", 2: "GND"})
    c.add("L1", "vreg_inductor", "3.3uH", {1: "VREG_LX", 2: "VDD_CORE"})

    # --- crystal: XIN direct, XOUT via 1k; 2520-4P pins 1/3 xtal, 2/4 GND ---
    c.add("Y1", "crystal", "12MHz", {1: "XIN", 2: "GND", 3: "XTAL_R", 4: "GND"})
    c.add("R1", "r_1k", "1k", {1: "XTAL_R", 2: "XOUT"})
    c.add("C14", "c_15p", "15p", {1: "XIN", 2: "GND"})
    c.add("C15", "c_15p", "15p", {1: "XTAL_R", 2: "GND"})

    # --- RUN / BOOTSEL / SWD ---
    c.add("R2", "r_10k", "10k", {1: "RUN", 2: "3V3"})
    c.add("SW1", "bootsel_button", "BOOTSEL", {1: "BOOTSEL_SW", 2: "GND"})
    c.add("R3", "r_1k", "1k", {1: "BOOTSEL", 2: "BOOTSEL_SW"})
    c.add("TP1", "testpoint", "RUN", {1: "RUN"})
    c.add("TP2", "testpoint", "SWCLK", {1: "SWCLK"})
    c.add("TP3", "testpoint", "SWDIO", {1: "SWDIO"})

    # --- USB-C ---
    c.add("J1", "usb_conn", "USB-C", {
        "A1B12": "GND", "B1A12": "GND",
        "A4B9": "VBUS", "B4A9": "VBUS",
        "A5": "CC1", "B5": "CC2",
        "A6": "USB_DP_C", "B6": "USB_DP_C",
        "A7": "USB_DM_C", "B7": "USB_DM_C",
        "A8": "", "B8": "",
        1: "GND", 2: "GND", 3: "GND", 4: "GND",  # shell legs
    })
    c.add("R4", "r_5k1", "5.1k", {1: "CC1", 2: "GND"})
    c.add("R5", "r_5k1", "5.1k", {1: "CC2", 2: "GND"})
    c.add("U5", "usb_esd", "USBLC6-2P6", {
        1: "USB_DP_C", 6: "USB_DP_C", 3: "USB_DM_C", 4: "USB_DM_C",
        5: "VBUS", 2: "GND",
    })
    c.add("R6", "r_27", "27", {1: "USB_DP_C", 2: "USB_DP"})
    c.add("R7", "r_27", "27", {1: "USB_DM_C", 2: "USB_DM"})

    # --- charger (LGS4056H DFN2x2-8) ---
    rprog = design["power"].get("charge_current_ma", 40)
    rprog_val = "22k"  # 900/22k ≈ 41mA; change part r_22k if design changes
    c.add("U2", "charger", "LGS4056H", {
        1: "GND",        # TEMP grounded -> NTC disabled
        2: "PROG",
        3: "GND",
        4: "VBUS",       # VCC
        5: "VBATT",      # BAT
        6: "",           # DONE NC
        7: "CHRG",
        8: "VBUS",       # CE high = enabled
        9: "GND",        # EP
    })
    c.add("R8", "r_22k", rprog_val, {1: "PROG", 2: "GND"})
    c.add("C16", "c_10u_0603", "10u", {1: "VBUS", 2: "GND"})
    c.add("C17", "c_10u_0603", "10u", {1: "VBATT", 2: "GND"})
    # charge LED: VBUS -> R -> LED -> CHRG (lights while charging)
    c.add("R9", "r_1k", "1k", {1: "VBUS", 2: "CHRG_A"})
    c.add("D1", "chrg_led", "RED", {2: "CHRG_A", 1: "CHRG"})  # 2=A, 1=K per 0603 LED fp

    # --- ear-wire loop (mechanical) ---
    c.add("H1", "hanger", "HANGER", {})

    # --- battery ---
    c.add("BT1", "battery_clip", "LIR2032", {1: "VBATT", 2: "GND"})

    # --- 3.3V LDO ---
    c.add("U3", "ldo", "NCP730-3.3", {
        1: "3V3", 2: "", 3: "GND", 4: "VBATT", 5: "", 6: "VBATT", "EP": "GND",
    })  # 1=OUT 3=GND 4=EN 6=IN
    c.add("C18", "c_1u", "1u", {1: "VBATT", 2: "GND"})
    c.add("C19", "c_1u", "1u", {1: "3V3", 2: "GND"})

    # --- LED power switch ---
    c.add("U4", "load_switch", "TPS22913", {
        "A2": "VBATT", "A1": "VLED", "B1": "GND", "B2": "LED_EN",
    })
    c.add("R10", "r_10k", "10k", {1: "LED_EN", 2: "GND"})  # off at boot
    c.add("C20", "c_10u_0603", "10u", {1: "VLED", 2: "GND"})

    # --- battery voltage sense ---
    c.add("R11", "r_1m", "1M", {1: "VBATT", 2: "VBSENSE"})
    c.add("R12", "r_1m", "1M", {1: "VBSENSE", 2: "GND"})
    c.add("C21", "c_100n", "100n", {1: "VBSENSE", 2: "GND"})

    # --- LED ring: 1=DI 2=VCC 3=GND 4=DO ---
    bypass_every = design["leds"].get("bypass_every", 2)
    for i in range(n_leds):
        di = f"LED_D{i}"
        do = f"LED_D{i+1}" if i < n_leds - 1 else ""
        c.add(f"LED{i+1}", "led", "TBA-C1010MB", {1: di, 2: "VLED", 3: "GND", 4: do})
        if i % bypass_every == 0:
            c.add(f"C{30+i}", "c_100n", "100n", {1: "VLED", 2: "GND"})

    # resolve footprints/lcsc from parts.yaml
    for comp in c.components.values():
        p = parts[comp.part]
        comp.footprint = p["footprint"]
        comp.lcsc = p.get("lcsc", "")
    return c


if __name__ == "__main__":
    cir = build_circuit()
    print(f"{len(cir.components)} components, {len(cir.nets)} nets")
    for net, pads in sorted(cir.nets.items()):
        print(f"  {net:12s} {len(pads):3d} pads")
