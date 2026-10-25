#!/usr/bin/env python3
"""Circuit definition: components + nets for the simple_earring board.

This is the electrical source of truth. gen_board.py consumes build_circuit().

Pin references verified against:
  - RP2350 QFN-60 pin table (from rp2350a-compact, matches datasheet)
  - LGS4056H datasheet rev C (TEMP->GND disables NTC, I=900/R_PROG <300mA)
  - NCP730 WDFN-6, TPS22913 YZV 4-ball, USBLC6-2P6 SOT-666 (from earring)
  - WS2816C-1313/4P datasheet p.2 (1=VDD, 2=DO, 3=GND, 4=DI); was SK6805-EC10
RP2350A (RP2354A pinout, no internal flash): QSPI bus wired to external
W25Q16JVUXIQ (U7) per the official RPI-RP2350A-MINIMAL R4 (docs/);
QSPI_SS doubles as the BOOTSEL strap (Q7 + 1k to GND, driven by the power
button's long-hold timer) and U7's /CS.
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
# LED ring: three zones since 2026-10-24 (left / right / centre), each its
# own chain, load switch and level shifter, so a dark zone draws nothing.
# The three data pins are ADJACENT (GPIO16-18, pins 27-29, top-left after
# the MCU rotation, next to the zones' entry LEDs), so one PIO program can
# clock all three chains in parallel from consecutive pins.
GP_LED_DATA_C = 16  # pin 27 -> Q10 -> centre zone (LED38..45)
GP_LED_DATA_R = 17  # pin 28 -> Q9  -> right zone (LED37 -> LED19, reversed)
GP_LED_EN_R = 0     # pin 2, next to LED_EN_L's pin 3 -> U9 ON
GP_LED_EN_C = 22    # pin 34, west-column run after BTN_SENSE -> U10 ON
GP_LED_DATA = 18  # pin 29: lands top-left after the 180deg MCU rotation,
                  # right next to LED1 at the start of the ring
GP_LED_EN = 1     # -> U4 (left zone) ON
ADC_VBSENSE = 43  # GPIO29_ADC3 pin number
ADC_LIGHT = 40    # GPIO26_ADC0 pin number: ambient light sensor (rev 2)
ADC_VBUS = 41     # GPIO27_ADC1 pin number: USB cable present (rev 3)
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
# Power latch (LiPo change, 2026-10-22): the slide switch became a momentary
# button, so the CPU holds its own power on. Both take the unused west-column
# run after CHRG (pins 32-37 were all NC); the back interior they escape into
# is open now that BT1's Ø8 centre pad is gone. design/decisions.md.
GP_PWR_HOLD = 20  # pin 32: high = keep the LDO enabled (-> Q5 gate)
GP_BTN_SENSE = 21 # pin 33: power button held, ACTIVE HIGH (Q8 drives it,
                  # R27 pulls it down). NO internal pull-up: see the one-button
                  # block. Old latch firmware read it pulled-up/active-low.
GP_CHRG_DONE = 28 # pin 42: low when charge complete

# LED pin numbering. WS2816C-1313/4P (since 2026-10-24): 1=VDD, 2=DO,
# 3=GND, 4=DI (Worldsemi ds p.2; top view VDD TL, DI TR, DO BL, GND BR, 0.8mm
# grid). That is the SK6805's cyclic pin order rotated 90deg, so DI/DO stay
# on opposite corners and the 45deg diamond ring scheme is unchanged.
# Was: SK6805-EC10 1=GND 2=DIN 3=VDD 4=DOUT (DI TL, VDD BL, GND TR, DO BR,
# 0.68mm grid); before that TBA-C1010MB 1=DI 2=VCC 3=GND 4=DO.
# place.py / gen_schematic.py read DI/DO/VDD from here; keep this the single
# source of truth when swapping LED parts.
LED_PIN = {"VDD": 1, "DO": 2, "GND": 3, "DI": 4}


def led_zones(design):
    """Zone -> LED numbers in CHAIN order (data enters the first one).
    Perimeter LED1..ring_count runs top-left, down the left side, round the
    bottom and up the right; the tip chevron follows right-to-left; the
    interior octagon is last. Left = LED1..18. Right = the rest of the
    perimeter plus the chevron, chained in REVERSE (LED37 -> LED19), so its
    data enters at the top-left beside the left zone's. Centre = interior."""
    n = design["leds"]["count"]
    ring = design["leds"]["ring_count"]
    tip = n - ring - design["leds"].get("inner_count", 0)
    split = 18
    return {"L": list(range(1, split + 1)),
            "R": list(range(ring + tip, split, -1)),
            "C": list(range(ring + tip + 1, n + 1))}


def led_zone_of(design):
    return {i: z for z, chain in led_zones(design).items() for i in chain}


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
    u1[GPIO[GP_LED_DATA]] = "LED_DATA_L"  # -> Q3 gate, NOT the ring directly
    u1[GPIO[GP_LED_DATA_R]] = "LED_DATA_R"
    u1[GPIO[GP_LED_DATA_C]] = "LED_DATA_C"
    u1[GPIO[GP_LED_EN]] = "LED_EN_L"
    u1[GPIO[GP_LED_EN_R]] = "LED_EN_R"
    u1[GPIO[GP_LED_EN_C]] = "LED_EN_C"
    u1[ADC_VBSENSE] = "VBSENSE"
    u1[ADC_LIGHT] = "LIGHT"
    u1[ADC_VBUS] = "VBUS_SENSE"
    u1[GPIO[GP_I2C_SDA]] = "IMU_SDA"
    u1[GPIO[GP_I2C_SCL]] = "IMU_SCL"
    u1[GPIO[GP_IMU_INT1]] = "IMU_INT1"
    u1[GPIO[GP_CHRG]] = "CHRG"
    u1[GPIO[GP_CHRG_DONE]] = "CHRG_DONE"
    u1[GPIO[GP_PWR_HOLD]] = "PWR_HOLD"
    u1[GPIO[GP_BTN_SENSE]] = "BTN_SENSE"
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
    # (SW1, the SKRPAME010 BOOTSEL key, is gone — 2026-10-24, user decision:
    # a long hold on the power button now does its job. BOOTSEL_SW is driven
    # by Q7 in the one-button block below; R3 is unchanged.)
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
    rprog_val = "18k"  # 900/18k = 50mA (0.36C) under the LPR302823's 70mA
                       # max — design/parts/r8-rprog.md. Change r_18k with it.
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
    c.add("R8", "r_18k", rprog_val, {1: "PROG", 2: "GND"})
    c.add("C16", "c_10u_0603", "10u", {1: "VBUS", 2: "GND"})
    c.add("C17", "c_10u_0603", "10u", {1: "VBATT", 2: "GND"})
    # (no charge LED: CHRG/DONE go straight to GPIOs with internal
    # pull-ups; software owns the charge indication)

    # --- battery ---
    # BT1 is two bare solder pads for the LiPol LPR302823's wires (round
    # Ø28 LiPo, taped to the back — design/intent.md, design/brief.md).
    # No LCSC part, so it stays out of the JLC BOM/CPL like the test points,
    # and its value can name the cell without contradicting an LCSC column.
    # (Through 4538da2 BT1 was the MY-2032-12-R coin clip.)
    c.add("BT1", "battery_pads", "LPR302823", {1: "VBATT", 2: "GND"})

    # --- power path (rev 2): the board runs off VBUS when a cable is in ---
    # Rev 1 hung the LDO input and the LED load switch on VBATT, the same
    # node as the charger's BAT pin, so the ~41mA program current was SHARED
    # with the running system: 17mA MCU + 17.5mA LED rail left ~6mA for the
    # cell, and a flat cell could never climb to the SK6805's 3.7V floor
    # before someone unplugged it. Splitting the rails fixes that at the
    # root instead of raising I_prog (the R8 22k->15k rework, now dropped:
    # 22k = 40.9mA is exactly the RJD2032C1's rated 40mA, and with the
    # system off the cell it ALL reaches the cell in either switch
    # position — the SW2-off overcurrent hazard that blocked 15k is gone).
    #
    #   VBUS --|>|-- VSYS      D3, blocking SILICON rectifier (~0.8V; see D3)
    #   VBATT --Q2-- VSYS      P-FET, ON only when no cable is present
    #   VSYS  -> U3 (LDO IN), U4 (LED load switch IN)
    #   VBATT -> U2 pin 5 (charger BAT), BT1, C17, SW2  [cell node ONLY]
    #
    # Q2 ORIENTATION: source = VSYS, drain = VBATT. A P-FET's body diode
    # conducts drain->source, so this way it points cell->VSYS: it BLOCKS
    # the USB rail from back-feeding the cell around the charger (wiring it
    # the intuitive way, source on the battery, would dump ~4.7V straight
    # into the cell through the body diode), while still letting the cell
    # carry the load through ~0.4V of diode if VSYS sags under VBATT —
    # which is what covers the ~200ms of VBUS decay on unplug.
    #
    # Gate: R22 (10k) from VBUS, R21 (1M) to GND, so the gate sits at
    # essentially VBUS when a cable is in (Vgs = +0.25V vs VSYS -> hard
    # off) and follows the dead VBUS node when it is out. That node is NOT
    # floating: R19/R20 (20k, below) pin it to <=0.65V even against R18's
    # backfeed, so Vgs = -2.4V at a 3.0V cell -> Q2 fully on (Rds(on) is
    # specified 210mOhm at -1.8V). The 10k is also the gate's only defence
    # against hot-plug ringing; 1M:10k keeps the divider loss at 5uA.
    #
    # What this buys, beyond charge current: DONE can finally assert (the
    # cell's current tapers to ITERM because the system is no longer
    # hanging off it — main.cpp:670's "DONE never asserts while awake" is
    # a rev-1 limitation), VBSENSE reads a TRUE UNLOADED cell voltage while
    # charging (so chargePct's 150mV IR fudge should drop to ~28mV of real
    # charger IR — see the RJD2032C1's <=700mOhm), the ring lights up on a
    # dead cell, and the board runs with no cell fitted at all.
    #
    # COST: VSYS is ~4.7V, and SK6805 VIH = 0.7*VDD = 3.29V there (3.5V at
    # a 5.25V port) — above what a 3.3V IOVDD pad can drive. That is what
    # Q3/R23 down in the LED section are for. Diode-dropping VSYS into the
    # LED's window instead does NOT work: two Schottkys land at 4.3V typ
    # but 3.8V at the low corner (under the 3.7V floor) and 4.65V at the
    # high one (VIH 3.26V, still failing) — the window is narrower than
    # the corners, so the level has to be shifted, not the rail.
    c.add("Q2", "oring_pfet", "CJ2101", {1: "PATH_GATE", 2: "VSYS", 3: "VBATT"})
    # D3 is SILICON (1N4007WS), not the B5819WS Schottky it was through
    # afabd86. design/sim/button found the Schottky's reverse leakage, from
    # VSYS into the dead VBUS node (~120uA at 75C, Yangjie Fig. 4), lifts
    # VBUS through R19+R20 and R18/R17 couple half of it onto the LDO EN:
    # with D2's leak (below) the board switched ITSELF on at ~70C. The
    # 1N4007WS leaks ~1uA at 85C (MDD Fig. 2, typ), i.e. 20mV on VBUS.
    # Price: VF ~0.8V at 100mA (MDD Fig. 3) instead of ~0.3V, so VSYS is
    # ~4.2V on a 5.0V port and ~3.7V on a 4.5V one — the SK6805 floor. At a
    # weak port with a full cell, Q2's body diode lets the cell carry some
    # of the load; harmless (the charger just sees a lighter cell).
    # Dissipation <=0.12W at the firmware's 140mA system cap.
    c.add("D3", "sys_diode", "1N4007WS", {1: "VSYS", 2: "VBUS"})  # 1 = cathode
    c.add("R21", "r_1m", "1M", {1: "PATH_GATE", 2: "GND"})
    c.add("R22", "r_10k", "10k", {1: "VBUS", 2: "PATH_GATE"})
    c.add("C29", "c_10u_0603", "10u", {1: "VSYS", 2: "GND"})

    # --- 3.3V LDO, EN = power latch OR USB (rev 2: USB boots the chip
    # even with the latch off, so plugged-in charging can be indicated).
    # The notes below were written for the SW2 slide switch; "switch on"
    # now reads "latch held or button pressed" (see the latch block). ---
    # (MSK12C02 contacts are 50mA-rated: switch the EN signal, not the
    # battery current; SPDT gives clean VBATT/GND levels both positions.)
    # SW2's common is now SW_ON (VBATT on / GND off), no longer wired
    # straight to EN — D2 (BAV99W, two SILICON diodes in SERIES: 1=A1, 2=K2,
    # 3=K1+A2 midpoint, Nexperia ds Table 2 — the BAT54SW pinout) sits between:
    #   diode 1 (SW_ON -> PWR_EN): the switch still enables the LDO
    #     (EN = VBATT - ~0.2V, far above the 1.05V max rising threshold);
    #   diode 2 (PWR_EN -> VBATT): clamps EN to VBATT + Vf. Required:
    #     (silicon since 2026-10-24: a Schottky here leaked ~20uA at 85C from
    #     VBATT into R17's 100k = 2V on EN, half of the hot self-start found
    #     by design/sim/button. BAV99W IR <= 30nA @25V/25C. The clamp is now
    #     VBATT + ~0.6V, still under VIN + 0.3 because EN is only ever driven
    #     to VBATT - 0.6 (SW_ON via diode 1) or VBUS/2 (R18) — the clamp only
    #     engages for a dead cell under USB, where VSYS is VBUS - 0.8.)
    #     NCP730 abs max V_EN is (V_IN + 0.3), NOT an independent rating
    #     — a bare diode from 5V VBUS would violate it whenever
    #     VBUS - 0.3 > VBATT + 0.3, i.e. essentially always.
    # R18 feeds VBUS into PWR_EN through 100k against R17's 100k
    # pulldown: USB present -> EN ~ VBUS/2 (2.2-2.6V), clamped by
    # diode 2 to VBATT + ~0.2 when the cell is low (precharge of a dead
    # cell can sit below 2.5V), so EN stays inside abs max AND above
    # threshold -> the chip boots. R17 is 100k, not 1M: EN has an
    # internal pull-up to VIN (up to 1uA, ds p5) and a falling
    # threshold as low as 0.5V; 100k holds EN <= 0.1V worst-case with
    # switch off + no USB. Costs ~40uA through D2/R17 while the switch
    # is on — noise next to the mA-scale LED load.
    # (With SW2 on and no USB, EN backfeeds ~35uA through R18 into the
    # dead VBUS node and floats it near VBATT. Harmless: the charger's
    # VCC stays below VBAT so it sleeps, and the current is capped by
    # R18. Blocking it would cost a third diode for zero benefit.)
    # (Rev-2 power path: IN is VSYS now, not VBATT. The D2 clamp still
    # references VBATT and is still legal — V_EN max is V_IN + 0.3 and
    # VSYS >= VBATT in every state, so clamping to the LOWER of the two is
    # conservative. NCP730 is a 38V-input part, so the 4.7V USB rail is a
    # non-event for it; it just drops 1.4V instead of 0.3V at ~20mA.)
    c.add("U3", "ldo", "NCP730-3.3", {
        1: "3V3", 2: "", 3: "GND", 4: "PWR_EN", 5: "", 6: "VSYS", "EP": "GND",
    })  # 1=OUT 3=GND 4=EN 6=IN
    # --- soft power latch (LiPo change): SW_ON is no longer a slide
    # switch's common. It is the drain of Q4, a high-side P-FET that is ON
    # while the power button is held OR while the CPU holds PWR_HOLD high.
    # Everything downstream of SW_ON (D2 -> PWR_EN, the R11/R12 VBSENSE
    # divider) is untouched, so "SW_ON = VBATT" still means "on" and
    # VBSENSE keeps both its jobs. Why the slide switch had to go: the
    # LPR302823's Ø28 outline covers SW2's old spot at every legal angle
    # (design/gates/phase4.md M1).
    #   press:   BTN_N -> GND; D4 A2 pulls LATCH_G to ~0.3V; Q4 on;
    #            SW_ON = VBATT -> D2 -> PWR_EN -> LDO up -> CPU boots
    #   latch:   firmware drives PWR_HOLD high first thing in boot; Q5 holds
    #            LATCH_G low after the button is released
    #   off:     long press -> firmware drops PWR_HOLD; power falls when the
    #            button is released (D4 A2 holds Q4 on until then)
    #   sense:   D4 A1 pulls PRESS_N low while pressed; Q8 turns that into
    #            an active-high BTN_SENSE (one-button block below). When the
    #            board is OFF, BTN_N sits at ~VBATT via D4 A2 + R24 and
    #            PRESS_N is at 0V (3V3 is down), so A1 is REVERSE-biased.
    # The leaks that can false-trigger Q4 when off are D4 A1's REVERSE
    # current (into the dead PRESS_N node), D6's (the TVS) and Q5's IDSS,
    # all through R24 (and see Q4's threshold note below). That is why D4 is a
    # SILICON pair (BAV70W, IR <= 25nA @20V/25C, ds DS30063 p.2) and not a
    # Schottky: a BAT54's reverse current at 4V is ~20uA by 85C (Nexperia
    # BAT54W Fig. 2), which through 100k is 2V — enough to switch Q4 on by
    # itself in a hot car. The budget on LATCH_G is Q4's |VGS(th)| min
    # (0.8V since the LBSS84WT1G swap; it was the CJ2101's 0.45V) minus its
    # tempco and the subthreshold current R17 turns into EN volts.
    # BAV70W at 4V/85C is ~1uA -> 0.1V. Gate-1/latch review,
    # design/gates/phase2.md; adoption review F2, design/gates/phase8.md.
    # (D4 A1 now drives PRESS_N, not the GPIO: the one-button block.)
    # R24 stays 100k (42uA while on). D6 (TVS) adds <=100nA at 25C (ds
    # IRM max at 5V; ~1uA hot by its Fig. 6) — simulated, design/sim/button.
    # USB still enables the LDO through R18 whatever the latch says.
    # (Pin orders on the symmetric parts — SW2's two terminals, R24's ends,
    # D4's two identical anodes — are chosen so the schematic block draws
    # with power on top and ground below; electrically interchangeable.)
    c.add("SW2", "power_button", "PWR", {1: "GND", 2: "BTN_EXT"})
    # ESD (gate-8 S4, design/sim/button): the button sits on the board edge
    # under a fingertip. With only C27 on the line, a -8kV contact discharge
    # (150pF/330R) put ~24A through D4 (IFSM 2A) and the strike itself
    # registered as a press. D6 clamps at the switch pad, and R30 then
    # isolates everything behind it: at the TVS's ~14V clamp only ~14mA can
    # reach C27/D4, which moves BTN_N by millivolts. R30 costs ~70mV on the
    # pressed level (LATCH_G ~0.5-0.7V, still >2.2V of Q4 gate drive) and nothing
    # on release (C27 recharges through R24, not R30).
    c.add("D6", "tvs_bidir", "PESD5V0S1BL", {1: "BTN_EXT", 2: "GND"})
    c.add("R30", "r_1k", "1k", {1: "BTN_EXT", 2: "BTN_N"})
    # Q4 is a HIGH-THRESHOLD P-FET (LBSS84WT1G, |VGS(th)| 0.8-2.0V), not
    # the CJ2101 (0.45V min) it was through the first one-button pass.
    # Review F2 (design/gates/phase8.md, design/sim/button/leakstudy.py): with
    # 0.45V and R24 100k, the board-off leaks into LATCH_G (D4 A1, D6, Q5
    # IDSS) put EN at 0.67V at 85C if the threshold falls 3mV/C, and the
    # CJ2101 datasheet gives no tempco. Q4 carries only SW_ON's ~30uA, so
    # a weak, high-threshold part costs nothing: EN stays 0.07V there. Turn-on:
    # pressed LATCH_G ~0.7V -> VGS -2.3V at a 3.0V cell vs -2.0V max VGS(th).
    c.add("Q4", "latch_pfet", "LBSS84WT1G", {1: "LATCH_G", 2: "VBATT", 3: "SW_ON"})
    c.add("R24", "r_100k", "100k", {1: "VBATT", 2: "LATCH_G"})
    c.add("Q5", "lvl_nfet", "BSS138W", {1: "PWR_HOLD", 2: "GND", 3: "LATCH_G"})
    c.add("R25", "r_100k", "100k", {1: "PWR_HOLD", 2: "GND"})  # off at boot
    c.add("D4", "cc_diode", "BAV70W", {1: "PRESS_N", 2: "LATCH_G", 3: "BTN_N"})
    # C27: debounce, and the second ESD stage behind D6/R30.
    # tau = R24 x C27 = 10ms on release; a press discharges it via R30
    # in 0.1ms.
    c.add("C27", "c_100n", "100n", {1: "BTN_N", 2: "GND"})
    c.add("D2", "or_diode", "BAV99W", {1: "SW_ON", 2: "VBATT", 3: "PWR_EN"})
    c.add("R17", "r_100k", "100k", {1: "PWR_EN", 2: "GND"})
    c.add("R18", "r_100k", "100k", {1: "VBUS", 2: "PWR_EN"})

    # --- one button: long hold = BOOTSEL / hardware force-off ---
    # (2026-10-24, user decision; simulated over corners in design/sim/button
    # before adoption.) SW1 is gone. Holding the power button ~2-11s (spread
    # over parts and temperature, ~5s typical) resets the chip with QSPI_SS
    # strapped low, so the bootrom comes up in BOOTSEL. Nothing in flash is
    # touched: with USB in it waits as a drive until unplugged/rebooted; on
    # battery the reset drops PWR_HOLD and the board turns OFF on release —
    # which is also the force-off for hung firmware the soft latch lacked
    # (gate-2 M2).
    #   PRESS_N  D4's spare anode, R26 to 3V3. ~0.45V (one silicon VF) while
    #            pressed. 0V when the board is off, so D4 A1 is reverse-biased
    #            exactly as when it went to the GPIO pad: the off-state leak
    #            budget on LATCH_G is unchanged.
    #   Q8       P-FET inverter from 3V3: BTN_SENSE (GPIO21) becomes a clean
    #            active-high 0/3.3V "held". A P-FET because the 0.45V diode-OR
    #            low is too close to a Schmitt's VT- (0.6V min), but is 2.85V
    #            of gate drive against CJ2101's -0.45..-1V threshold.
    #   R27 4.7k BTN_SENSE pull-down. Firmware that still enables GPIO21's
    #            internal pull-up (32-86k) then holds the node at <=0.42V;
    #            add U8's input leak at its +1uA spec max x R28 (0.68V) and
    #            BOOT_TMR is still 1.1V, under VT+ min (1.42V at 3.3V), so
    #            the timer can't creep up by itself (review F4: 10k left only
    #            ~0.05V). Costs 0.7mA only while the button is held. FIRMWARE MUST CHANGE WITH THIS BOARD:
    #            pull-up off, high = pressed, long-press-off well under 2s.
    #   R28/C75  hold timer, tau 6.8s nominal, charged from BTN_SENSE. 680k so
    #            U8's input leakage (+-1uA spec max, nA real) stays small
    #            next to the ~3uA charge current. C75 is X5R: tolerance,
    #            temperature and DC bias are all in the sim's ctmr corner
    #            (0.70 hot .. 1.10 cold), which sets the 2.2-10.3s window
    #            (2.0-19.4s with U8's II at its +-1uA spec max).
    #   D5       empties C75 into R27 the moment the button is released, so
    #            holds don't accumulate across presses.
    #   U8       74LVC2G14: BOOT_TMR -> LONG_N -> LONG (one clean edge).
    #   Q7       LONG pulls BOOTSEL_SW low -> R3 -> QSPI_SS: the strap the
    #            bootrom samples, held for as long as the button is.
    #   C76/R29  differentiate LONG's rising edge into a ~10ms gate pulse
    #            (10n x 1M: 8-14ms over Q6's VGS(th) 0.8-1.5V). 10n, not
    #            100n: the edge spike out of U8 is still ~VCC/25R, but it now
    #            moves 33nC for ~0.25us instead of 330nC (review F5):
    #   Q6       pulls RUN low -> the chip resets and finds CSn strapped low.
    # Everything here runs from 3V3, so with the board off it is unpowered
    # and draws nothing; while on, R26/R27 cost nothing unless pressed.
    c.add("R26", "r_100k", "100k", {1: "3V3", 2: "PRESS_N"})
    c.add("Q8", "oring_pfet", "CJ2101", {1: "PRESS_N", 2: "3V3", 3: "BTN_SENSE"})
    c.add("R27", "r_4k7", "4.7k", {1: "BTN_SENSE", 2: "GND"})
    c.add("R28", "r_680k", "680k", {1: "BTN_SENSE", 2: "BOOT_TMR"})
    c.add("C75", "c_10u_0603", "10u", {1: "BOOT_TMR", 2: "GND"})
    c.add("D5", "si_diode", "1N4148WS", {1: "BTN_SENSE", 2: "BOOT_TMR"})  # 1 = K
    c.add("U8", "logic_schmitt2", "74LVC2G14", {
        1: "BOOT_TMR", 6: "LONG_N",      # 1A -> 1Y
        3: "LONG_N", 4: "LONG",          # 2A -> 2Y
        5: "3V3", 2: "GND",
    })
    c.add("C77", "c_100n", "100n", {1: "3V3", 2: "GND"})  # U8 VCC decap
    c.add("Q7", "lvl_nfet", "BSS138W", {1: "LONG", 2: "GND", 3: "BOOTSEL_SW"})
    c.add("C76", "c_10n", "10n", {1: "LONG", 2: "RUN_KICK"})
    c.add("R29", "r_1m", "1M", {1: "RUN_KICK", 2: "GND"})
    c.add("Q6", "lvl_nfet", "BSS138W", {1: "RUN_KICK", 2: "GND", 3: "RUN"})

    # --- VBUS presence sense -> ADC1 (rev 3) ---
    # CHRG/DONE cannot distinguish "unplugged" from "plugged in and
    # FINISHED": when the charger terminates, both open-drain pins
    # release, so the level indicator loses its only evidence a cable is
    # attached and the green/full state becomes unreachable. Observed on
    # the bench Aug 25: cell full at 4.11V, USB in, chrg=0 done=0, and
    # the firmware correctly (but uselessly) fell back to the drip show.
    #
    # 10k:10k, deliberately NOT the 100k/1M used elsewhere, and the low
    # impedance IS the design: with SW2 on and no USB, PWR_EN backfeeds
    # through R18 (100k) and floats this otherwise-dead node — a
    # high-impedance divider would read that as "plugged in". A stiff 20k
    # tap swamps the backfeed instead, so no third blocking diode is
    # needed (the option weighed and rejected above for lack of benefit):
    #   no cable, SW2 on : VBUS = 3.9 * 20/(100+20) = 0.65V -> tap 0.33V
    #   cable, VBUS 4.4-5.5V                                -> tap 2.2-2.75V
    # Sample on ADC1 and threshold near 1.2V: >0.8V of margin either way,
    # and the tap stays under 3.3V at the 5.5V VBUS ceiling.
    #
    # Costs ~32uA from the cell while SW2 is on and USB is out (the tap
    # is the backfeed's new load). Same order as R17's existing ~40uA and
    # ~0.2% of active LED-mode current, so it is in line with choices the
    # design already makes. A blocking diode would reclaim it if wanted.
    #
    # Rev 2 gave this divider a SECOND job: it is what guarantees the dead
    # VBUS node is a defined low (<=0.65V) rather than a float, and Q2's
    # gate hangs off that node through R22. Do not delete or raise R19/R20
    # without re-checking Q2 — a floating VBUS near VBATT would leave the
    # gate near the source and switch the battery path OFF, i.e. a board
    # that only runs on USB.
    c.add("R19", "r_10k", "10k", {1: "VBUS", 2: "VBUS_SENSE"})
    c.add("R20", "r_10k", "10k", {1: "VBUS_SENSE", 2: "GND"})
    c.add("C18", "c_1u", "1u", {1: "VSYS", 2: "GND"})  # NCP730 IN decap
    c.add("C19", "c_1u", "1u", {1: "3V3", 2: "GND"})

    # --- LED power switch (rev 2: fed from VSYS, so the ring runs off the
    # cable when one is in — including with a cell too flat to reach the
    # SK6805's 3.7V floor, which is exactly when the charge gauge has to
    # be readable). TPS22913 max VIN is 5.5V; VSYS tops out ~4.95V at a
    # 5.25V port. ---
    # Three zones (2026-10-24): one switch per zone, so the WS2816C's
    # 0.7-1.0mA idle per LED is only paid where something is lit. An
    # unpowered zone must also be a separate CHAIN: data can't pass through
    # a dark LED, and a driven DI into an unpowered part back-feeds it
    # through its input clamp (VI max VDD+0.7). Hence per-zone shifters
    # below, each pulled up to its OWN zone rail.
    for u, r, cap, z in (("U4", "R10", "C20", "L"), ("U9", "R33", "C78", "R"),
                         ("U10", "R34", "C79", "C")):
        c.add(u, "load_switch", "TPS22913", {
            "A2": "VSYS", "A1": f"VLED_{z}", "B1": "GND", "B2": f"LED_EN_{z}",
        })
        c.add(r, "r_10k", "10k", {1: f"LED_EN_{z}", 2: "GND"})  # off at boot
        c.add(cap, "c_10u_0603", "10u", {1: f"VLED_{z}", 2: "GND"})

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

    # --- battery voltage / switch-position sense ---
    # Divider top is SW_ON (the switch common), not VBATT (rev 2):
    #   switch ON  -> VBSENSE = VBATT/2, battery telemetry exactly as
    #                 before (SW_ON = VBATT with no diode in between);
    #   switch OFF -> VBSENSE = 0. A running chip reading 0 here can
    #                 only be USB-powered with the switch off — that is
    #                 the whole mode signal for charge-indicator mode.
    # No new GPIO, no new escape from the jammed pin-40..43 west window,
    # and the divider's 2uA drain now stops when the switch is off.
    #
    # THE POWER PATH DOES NOT TOUCH THIS, deliberately: SW2 pin 1 stays on
    # VBATT (the cell), never VSYS. Wire it to VSYS and the reading becomes
    # VSYS/2 = 2.35V whenever a cable is in — a constant that says nothing
    # about either the cell or the switch. On VBATT the two signals stay
    # separable in all four states, with VBUS_SENSE (ADC1) as the cable bit:
    #   cable out, SW2 on : VBUS_SENSE 0.33V, VBSENSE VBATT/2 -> run, gauge
    #   cable out, SW2 off: board unpowered
    #   cable in,  SW2 on : VBUS_SENSE 2.2-2.75V, VBSENSE VBATT/2 -> dock,
    #                       and the cell is now UNLOADED, so this is the
    #                       first honest state-of-charge reading the design
    #                       has ever had while charging
    #   cable in,  SW2 off: VBUS_SENSE 2.2-2.75V, VBSENSE 0 -> dock, no
    #                       percentage. Still the accepted rev-2 trade (all
    #                       four ADC-capable pins, 40-43, are spoken for) —
    #                       but much cheaper now, because with the system
    #                       off the cell CHRG/DONE finally mean what they
    #                       say, so red/green is real information.
    # (Cost: no VBATT reading while in charge-only mode. Nothing is
    # lost: during CV charge the charger pins VBATT at 4.2V anyway, so
    # the voltage carries no charge-state information; CHRG/DONE are
    # the real signals there.)
    c.add("R11", "r_1m", "1M", {1: "SW_ON", 2: "VBSENSE"})
    c.add("R12", "r_1m", "1M", {1: "VBSENSE", 2: "GND"})
    c.add("C21", "c_100n", "100n", {1: "VBSENSE", 2: "GND"})

    # --- ambient light sensor (rev 2): visible-light phototransistor ---
    # ALS-PT19-315C ds p6 app circuit: C (pin 1) -> 3V3, E (pin 2) -> the
    # LIGHT node, load R + filter C to GND (RL*CL >= 0.5 kOhm*uF). 22k
    # load: ~16mV in a dark room, 0.33V @ 100 lux, saturates ~900 lux.
    # LIGHT reads on ADC0 (GPIO26, pin 40). MUST be on the FRONT (faces
    # the world when worn); keep it away from the LEDs it meters.
    c.add("Q1", "light_sensor", "ALS-PT19", {1: "3V3", 2: "LIGHT"})
    c.add("R16", "r_22k", "22k", {1: "LIGHT", 2: "GND"})
    c.add("C26", "c_100n", "100n", {1: "LIGHT", 2: "GND"})

    # --- LED data level shifter (rev 2, forced by the power path) ---
    # The ring's VIH is 0.7*VLED. On the cell that peaked at 2.94V and a
    # 3.3V pad drove it directly; on VSYS it is 3.29V typical and 3.5V at
    # the USB ceiling, so the MCU can no longer clock the first pixel.
    # Q3 is an open-drain inverter into the ring, R23 pulls LED_D0 up to
    # VLED itself, so the swing is always a full VLED rail whatever VLED
    # happens to be (3.0V cell -> 5.0V cable). Only pixel 1 ever needed
    # this — every downstream DI is driven by the previous DO at VLED.
    # 1k against ~15pF of pin + trace is a ~33ns edge, against the
    # protocol's 300ns T0H; it burns 4.7mA only while the line is low
    # mid-frame (~4% duty
    # in show mode), which is noise next to the ring itself.
    # main.cpp must add gpio_set_outover(LED_DATA, GPIO_OVERRIDE_INVERT)
    # for rev-2 boards — see parts.yaml lvl_nfet. DO NOT flash that to a
    # rev-1 board: there Q3 does not exist and the ring would see inverted
    # data.
    # (WS2816C keeps VIH = 0.7*VDD, so the shifters stay. One per zone,
    # each pulled up to its own zone rail: a dark zone's R is dead, so its
    # first DI is never driven above an unpowered VDD.)
    for q, r, z in (("Q3", "R23", "L"), ("Q9", "R31", "R"), ("Q10", "R32", "C")):
        c.add(q, "lvl_nfet", "BSS138W",
              {1: f"LED_DATA_{z}", 2: "GND", 3: f"LED{z}_D0"})
        c.add(r, "r_1k", "1k", {1: f"VLED_{z}", 2: f"LED{z}_D0"})

    # --- LED ring (pin numbers from LED_PIN), chained per zone ---
    # Net LED<z>_D<j> feeds the DI of the j-th LED in that zone's chain.
    pins = {}
    for z, chain in led_zones(design).items():
        for j, i in enumerate(chain):
            pins[i] = {LED_PIN["DI"]: f"LED{z}_D{j}",
                       LED_PIN["DO"]: f"LED{z}_D{j+1}" if j < len(chain) - 1 else "",
                       LED_PIN["VDD"]: f"VLED_{z}", LED_PIN["GND"]: "GND"}
    assert sorted(pins) == list(range(1, n_leds + 1)), "zones must cover the ring"
    zone_of = led_zone_of(design)
    bypass_every = design["leds"].get("bypass_every", 2)
    for i in range(n_leds):
        c.add(f"LED{i+1}", "led", "WS2816C-1313", pins[i + 1])
        if i % bypass_every == 0:
            c.add(f"C{30+i}", "c_100n", "100n",
                  {1: f"VLED_{zone_of[i + 1]}", 2: "GND"})

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
