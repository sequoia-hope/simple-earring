#!/usr/bin/env python3
"""Circuit definition: components + nets for the simple_earring board.

This is the electrical source of truth. gen_board.py consumes build_circuit().

Pin references verified against:
  - RP2350 QFN-60 pin table (from rp2350a-compact, matches datasheet)
  - LGS4056H datasheet rev C (TEMP->GND disables NTC, I=900/R_PROG <300mA)
  - NCP730 WDFN-6, TPS22913 YZV 4-ball, USBLC6-2P6 SOT-666 (from earring)
  - SK6805-EC10 datasheet REV.01 (1=GND, 2=DIN, 3=VDD, 4=DOUT)
RP2350A (RP2354A pinout, no internal flash): QSPI bus wired to external
W25Q16JVUXIQ (U7) per the official RPI-RP2350A-MINIMAL R4 (docs/);
QSPI_SS doubles as the BOOTSEL strap (button + 1k to GND) and U7's /CS.
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
    # QSPI bus (RP2350A: external flash; pin map verified against the
    # official RPI-RP2350A-MINIMAL R4 board in docs/)
    "QSPI_SD3": 55, "QSPI_SCLK": 56, "QSPI_SD0": 57,
    "QSPI_SD2": 58, "QSPI_SD1": 59,
    "GND": 61,  # EP
    "GPIO29_ADC3": 43,
}
GPIO = {n: n + 2 if n <= 15 else n + 11 for n in range(0, 26)}  # GPIO0->pin2 ... GPIO15->pin17? (see note)
# NOTE: QFN-60 GPIO pins are irregular; explicit map below overrides the naive one.
GPIO = {0: 2, 1: 3, 2: 4, 3: 5, 4: 7, 5: 8, 6: 9, 7: 10, 8: 12, 9: 13,
        10: 14, 11: 15, 12: 16, 13: 17, 14: 18, 15: 19, 16: 27, 17: 28,
        18: 29, 19: 31, 20: 32, 21: 33, 22: 34, 23: 35, 24: 36, 25: 37,
        26: 40, 27: 41, 28: 42}

# GPIO roles
GP_LED_DATA = 18  # pin 29: lands top-left after the 180deg MCU rotation,
                  # right next to LED1 at the start of the ring
GP_LED_EN = 1     # -> TPS22913 ON
ADC_VBSENSE = 43  # GPIO29_ADC3 pin number
# IMU on I2C1 + INT1: all on the chip's right side after the 180deg
# rotation, facing the IMU's back-east spot. The exact GPIOs are picked so
# each escape lines up with its own gap in the right IOVDD-decap column
# (pin9/pin5 straddle the middle gap, pin12 exits through the lower gap):
# at 0.4mm pin pitch the pin-to-decap corridor is single-lane, so escapes
# must not share corridor segments.
GP_I2C_SDA = 6    # I2C1 SDA, pin 9  (middle decap gap)
GP_I2C_SCL = 11   # I2C1 SCL, pin 15 (south passage below C2)
GP_IMU_INT1 = 8   # pin 12           (lower decap gap)
# Charger status: LGS4056H CHRG/DONE are open-drain -> GPIOs, read with
# internal pull-ups (low = active). The charge LED (old D1/R9) is gone —
# status is displayed in software.
# BOTH exit the WEST column and cross to U2 on In3 with committed vias
# (route.py). The east side has no spare capacity for even one newcomer:
# tip-row pins (GPIO12/13) cut SWCLK's lane; the NE corner fits two
# tracks and LED_EN owns them with margin only for itself (CHRG there
# routed, but pushed the east half over capacity — 29 attempts across 7
# builds always stranded one east net: SWCLK/IMU_SDA/IMU_INT1/USB_DM
# rotating by seed); pin 4 behind C6 can't escape at all.
# CHRG = GPIO19 (pin 31): west column SOUTH end — pins 31-36 are all
# unused, so the lane past their tips down around C1's south corner is
# private. In3 via (-4.6,-5.8), landing via-in-pad in U2 pad 7. (Trying
# to pair CHRG through the same C5/C22 window as CHRG_DONE jammed it:
# two committed via discs walled the window mouth and the pad-tip
# corridor is single-lane past pin 42 — CHRG_DONE/VBSENSE/USB_DP all
# stranded, 5-unc plateau.)
# CHRG_DONE = GPIO28 (pin 42): straight west out the window (only
# VBSENSE shares it), In3 vias (-4.6,1.35) -> (7.8,6.6) NE of U2/C16.
GP_CHRG = 19      # pin 31: low while charging
GP_CHRG_DONE = 28 # pin 42: low when charge complete

# LED pin numbering. SK6805-EC10: 1=GND, 2=DIN, 3=VDD, 4=DOUT.
# The PHYSICAL pad layout is identical to the old TBA-C1010MB it replaces
# (DI top-left, VDD bottom-left, GND top-right, DO bottom-right, ~0.7mm
# diagonal grid) — only the numbering differs, so the ring placement,
# 45-degree diamond orientation and locked chain arcs are unchanged.
# route.py reads DI/DO/VDD from here; keep this the single source of
# truth when swapping LED parts (TBA was 1=DI 2=VCC 3=GND 4=DO).
LED_PIN = {"GND": 1, "DI": 2, "VDD": 3, "DO": 4}


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
    for name in ("QSPI_SD0", "QSPI_SD1", "QSPI_SD2", "QSPI_SD3",
                 "QSPI_SCLK"):
        u1[RP_PINS[name]] = name
    u1[RP_PINS["XIN"]] = "XIN"
    u1[RP_PINS["XOUT"]] = "XOUT"
    u1[RP_PINS["SWCLK"]] = "SWCLK"
    u1[RP_PINS["SWD"]] = "SWDIO"
    u1[RP_PINS["RUN"]] = "RUN"
    u1[RP_PINS["ADC_AVDD"]] = "3V3"
    u1[RP_PINS["VREG_AVDD"]] = "VREG_AVDD"  # noise-sensitive: RC-filtered 3V3
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
    u1[GPIO[GP_I2C_SDA]] = "IMU_SDA"
    u1[GPIO[GP_I2C_SCL]] = "IMU_SCL"
    u1[GPIO[GP_IMU_INT1]] = "IMU_INT1"
    u1[GPIO[GP_CHRG]] = "CHRG"
    u1[GPIO[GP_CHRG_DONE]] = "CHRG_DONE"
    for p in GPIO.values():
        u1.setdefault(p, "")  # unused GPIOs NC
    c.add("U1", "mcu", "RP2350A", u1)

    # --- QSPI flash (RP2350A has none internally; RP2354A went OOS) ---
    # W25Q16JVUXIQ USON-8 2x3mm. /CS shares the BOOTSEL net with the
    # QSPI_SS strap (button + 1k), Pico-style — no series link. /WP and
    # /HOLD are QSPI_SD2/SD3: wired for quad-SPI XIP like the official
    # RPI-RP2350A-MINIMAL (docs/), which is also where the pin mapping
    # was taken from.
    c.add("U7", "flash", "W25Q16JVUXIQ", {
        1: "BOOTSEL",     # /CS
        2: "QSPI_SD1",    # DO (IO1)
        3: "QSPI_SD2",    # /WP (IO2)
        4: "GND",
        5: "QSPI_SD0",    # DI (IO0)
        6: "QSPI_SCLK",   # CLK
        7: "QSPI_SD3",    # /HOLD (IO3)
        8: "3V3",         # VCC
        9: "GND",         # center EP strip
    })
    c.add("C25", "c_100n", "100n", {1: "3V3", 2: "GND"})  # flash VCC decap

    # --- IOVDD / rail decoupling on MCU ---
    # (9 caps: 6 IOVDD + OTP_VDD + QSPI_IOVDD + ADC_AVDD. VREG_AVDD's
    # per-pin 100n was dropped — it has the dedicated 4u7 CFILT C22, and
    # a 10th cap made the right-side decap column wall off every escape
    # corridor to the back-east IMU cluster.)
    # C5 and C6 are NOT IOVDD decoupling. They already sit 1.39mm from DVDD
    # 39 and 1.63mm from DVDD 6 — the two core pins nearest the regulator —
    # so they are the 100n pair ds §6.1.3 asks for on the core rail, which
    # otherwise had only bulk 4u7 on it. IOVDD 38 and 1 fall back on C3
    # (2.10mm) and C4: the same "share a capacitor where the escape fan-out
    # leaves no room" trade the RP2350 hardware design guide §2.2.1
    # documents making on the official minimal board.
    CORE_DECAP = {5, 6}
    for i, _ in enumerate(RP_PINS["IOVDD"] + [53, 54, 44]):
        rail = "VDD_CORE" if i + 1 in CORE_DECAP else "3V3"
        c.add(f"C{i+1}", "c_100n", "100n", {1: rail, 2: "GND"})
    # VREG per RP2350 ds §6.3.8: CIN at VIN/PGND, COUT at the inductor,
    # C13 = second VDD_CORE cap near a DVDD pin, AVDD RC-filtered (33R+4u7)
    c.add("C11", "c_4u7", "4.7u", {1: "3V3", 2: "GND"})       # CIN
    c.add("C12", "c_4u7", "4.7u", {1: "VDD_CORE", 2: "GND"})  # COUT
    c.add("C13", "c_4u7", "4.7u", {1: "VDD_CORE", 2: "GND"})  # 2nd VOUT cap
    # (the 100n HF pair ds §6.1.3 wants on the core rail is C5/C6 above —
    # they were already sitting on the DVDD pins, just netted to 3V3)
    # L1 pad 1 = polarity-dot end; ds Fig 23 wants the dot on the VOUT side
    c.add("L1", "vreg_inductor", "3.3uH", {1: "VDD_CORE", 2: "VREG_LX"})
    c.add("R13", "r_33", "33", {1: "3V3", 2: "VREG_AVDD"})
    c.add("C22", "c_4u7", "4.7u", {1: "VREG_AVDD", 2: "GND"})

    # --- crystal: XIN direct, XOUT via 1k; 2520-4P pins 1/3 xtal, 2/4 GND ---
    c.add("Y1", "crystal", "12MHz", {1: "XIN", 2: "GND", 3: "XTAL_R", 4: "GND"})
    c.add("R1", "r_1k", "1k", {1: "XTAL_R", 2: "XOUT"})
    c.add("C14", "c_15p", "15p", {1: "XIN", 2: "GND"})
    c.add("C15", "c_15p", "15p", {1: "XTAL_R", 2: "GND"})

    # --- RUN / BOOTSEL / SWD ---
    c.add("R2", "r_10k", "10k", {1: "RUN", 2: "3V3"})
    # SKRPAME010 is a 4-terminal SPST tact. Only pads 1 and 4 are netted,
    # and that is deliberate: the LCSC footprint puts pads 1/3 on one side
    # of the body and 2/4 on the other, so the two contacts are the
    # SAME-SIDE pairs {1,3} and {2,4} — not {1,2}/{3,4} as the LCSC symbol
    # implies. Driving both pads of an assumed pair would have shorted
    # BOOTSEL_SW straight to GND and left the chip permanently strapped
    # into the USB bootloader. Pads 1 and 4 are diagonal, so they land on
    # opposite contacts under EITHER numbering convention; 2 and 3 are left
    # unnetted (still soldered, and internally tied to their partner) so the
    # strap is correct without needing the ALPS drawing to settle it.
    c.add("SW1", "bootsel_button", "BOOTSEL",
          {1: "BOOTSEL_SW", 2: "", 3: "", 4: "GND"})
    c.add("R3", "r_1k", "1k", {1: "BOOTSEL", 2: "BOOTSEL_SW"})
    c.add("TP1", "testpoint", "RUN", {1: "RUN"})
    c.add("TP2", "testpoint", "SWCLK", {1: "SWCLK"})
    c.add("TP3", "testpoint", "SWDIO", {1: "SWDIO"})

    # --- USB-C ---
    c.add("J1", "usb_conn", "USB-C", {
        "A1B12": "GND", "B1A12": "GND",
        "A4B9": "VBUS", "B4A9": "VBUS",
        "A5": "CC1", "B5": "CC2",
        "A6": "USB_C_DP", "B6": "USB_C_DP",
        "A7": "USB_C_DN", "B7": "USB_C_DN",
        "A8": "", "B8": "",
        1: "GND", 2: "GND", 3: "GND", 4: "GND",  # shell legs
    })
    c.add("R4", "r_5k1", "5.1k", {1: "CC1", 2: "GND"})
    c.add("R5", "r_5k1", "5.1k", {1: "CC2", 2: "GND"})
    c.add("U5", "usb_esd", "USBLC6-2P6", {
        1: "USB_C_DP", 6: "USB_C_DP", 3: "USB_C_DN", 4: "USB_C_DN",
        5: "VBUS", 2: "GND",
    })
    # ST's USBLC6-2 ds §3: the rail-to-rail clamp only works if VBUS is a
    # stiff reference during the surge, so where the run from the VBUS pin
    # to +VCC cannot be kept short they ask for a 100nF right at the part.
    # Our only VBUS bulk (C16) sits over at the charger, so add a local one.
    c.add("C28", "c_100n", "100n", {1: "VBUS", 2: "GND"})
    c.add("R6", "r_27", "27", {1: "USB_C_DP", 2: "USB_DP"})
    c.add("R7", "r_27", "27", {1: "USB_C_DN", 2: "USB_DM"})

    # --- charger (LGS4056H DFN2x2-8) ---
    rprog = design["power"].get("charge_current_ma", 40)
    rprog_val = "22k"  # 900/22k ≈ 41mA; change part r_22k if design changes
    c.add("U2", "charger", "LGS4056H", {
        1: "GND",        # TEMP grounded -> NTC disabled
        2: "PROG",
        3: "GND",
        4: "VBUS",       # VCC
        5: "VBATT",      # BAT
        6: "CHRG_DONE",  # DONE open-drain -> GPIO28 (low = charge complete)
        7: "CHRG",       # CHRG open-drain -> GPIO19 (low = charging)
        8: "VBUS",       # CE high = enabled
        9: "GND",        # EP
    })
    c.add("R8", "r_22k", rprog_val, {1: "PROG", 2: "GND"})
    c.add("C16", "c_10u_0603", "10u", {1: "VBUS", 2: "GND"})
    c.add("C17", "c_10u_0603", "10u", {1: "VBATT", 2: "GND"})
    # (no charge LED: CHRG/DONE go straight to GPIOs with internal
    # pull-ups; software owns the charge indication)

    # --- battery ---
    c.add("BT1", "battery_clip", "LIR2032", {1: "VBATT", 2: "GND"})

    # --- 3.3V LDO, gated by the back-side slide switch on EN ---
    # (MSK12C02 contacts are 50mA-rated: switch the EN signal, not the
    # battery current; SPDT gives clean VBATT/GND levels both positions)
    c.add("U3", "ldo", "NCP730-3.3", {
        1: "3V3", 2: "", 3: "GND", 4: "PWR_EN", 5: "", 6: "VBATT", "EP": "GND",
    })  # 1=OUT 3=GND 4=EN 6=IN
    c.add("SW2", "slide_switch", "PWR", {1: "VBATT", 2: "PWR_EN", 3: "GND"})
    c.add("C18", "c_1u", "1u", {1: "VBATT", 2: "GND"})
    c.add("C19", "c_1u", "1u", {1: "3V3", 2: "GND"})

    # --- LED power switch ---
    c.add("U4", "load_switch", "TPS22913", {
        "A2": "VBATT", "A1": "VLED", "B1": "GND", "B2": "LED_EN",
    })
    c.add("R10", "r_10k", "10k", {1: "LED_EN", 2: "GND"})  # off at boot
    c.add("C20", "c_10u_0603", "10u", {1: "VLED", 2: "GND"})

    # --- IMU (LSM6DS3TR-C LGA-14, back side, I2C mode 1) ---
    # ds application hints: CS->VDDIO selects I2C, SDx/SCx (unused aux
    # master) tied to VDDIO for lowest power, SDO/SA0->GND = addr 0x6A,
    # INT2 + NC pins left floating. INT1 = wake-on-motion to GPIO.
    # Pin numbers are from ST's Table 2 (DocID030071 rev 3) — the serial
    # trio at the top of the package is 12=CS, 13=SCL, 14=SDA. It used to be
    # entered here as 12=SCL/13=SDA/14=CS, which is the same three pins
    # rotated by one and is fatal: CS would have been driven by the I2C
    # clock (re-entering SPI mode on every edge) and SDA would have been
    # strapped hard to 3V3, so the part could never pull it low to ACK.
    c.add("U6", "imu", "LSM6DS3TR-C", {
        1: "GND",        # SDO/SA0 -> addr 0x6A
        2: "3V3",        # SDx
        3: "3V3",        # SCx
        4: "IMU_INT1",
        5: "3V3",        # VDDIO
        6: "GND", 7: "GND",
        8: "3V3",        # VDD
        9: "",           # INT2 NC
        10: "", 11: "",  # NC — "leave unconnected, soldered to PCB"
        12: "3V3",       # CS high = I2C mode
        13: "IMU_SCL",
        14: "IMU_SDA",
    })
    c.add("C23", "c_100n", "100n", {1: "3V3", 2: "GND"})  # IMU VDD decap
    c.add("C24", "c_100n", "100n", {1: "3V3", 2: "GND"})  # IMU VDDIO decap
    c.add("R14", "r_4k7", "4.7k", {1: "IMU_SDA", 2: "3V3"})
    c.add("R15", "r_4k7", "4.7k", {1: "IMU_SCL", 2: "3V3"})

    # --- battery voltage sense ---
    c.add("R11", "r_1m", "1M", {1: "VBATT", 2: "VBSENSE"})
    c.add("R12", "r_1m", "1M", {1: "VBSENSE", 2: "GND"})
    c.add("C21", "c_100n", "100n", {1: "VBSENSE", 2: "GND"})

    # --- LED ring (pin numbers from LED_PIN) ---
    bypass_every = design["leds"].get("bypass_every", 2)
    for i in range(n_leds):
        di = f"LED_D{i}"
        do = f"LED_D{i+1}" if i < n_leds - 1 else ""
        c.add(f"LED{i+1}", "led", "SK6805-EC10", {
            LED_PIN["DI"]: di, LED_PIN["VDD"]: "VLED",
            LED_PIN["GND"]: "GND", LED_PIN["DO"]: do})
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
