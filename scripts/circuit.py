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
    u1[GPIO[GP_LED_DATA]] = "LED_DATA"  # -> Q3 gate, NOT the ring directly
    u1[GPIO[GP_LED_EN]] = "LED_EN"
    u1[ADC_VBSENSE] = "VBSENSE"
    u1[ADC_LIGHT] = "LIGHT"
    u1[ADC_VBUS] = "VBUS_SENSE"
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
    # BT1 is the CLIP, not the cell: the clip is what JLC solders, so its
    # value must be the clip's MPN or the BOM Comment column contradicts the
    # LCSC column next to it (this said "LIR2032", then "RJD2032C1", for a
    # line whose LCSC has always been a retainer). The cell is hand-fitted
    # and in no netlist — it is named in design.yaml's power.battery and in
    # the charger block's title in gen_schematic.py.
    c.add("BT1", "battery_clip", "MY-2032-12-R", {1: "VBATT", 2: "GND"})

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
    #   VBUS --|>|-- VSYS      D3, blocking Schottky (~0.3V at our ~60mA)
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
    c.add("D3", "sys_diode", "B5819WS", {1: "VSYS", 2: "VBUS"})  # 1 = cathode
    c.add("R21", "r_1m", "1M", {1: "PATH_GATE", 2: "GND"})
    c.add("R22", "r_10k", "10k", {1: "VBUS", 2: "PATH_GATE"})
    c.add("C29", "c_10u_0603", "10u", {1: "VSYS", 2: "GND"})

    # --- 3.3V LDO, EN = slide switch OR USB (rev 2: USB boots the chip
    # even with SW2 off, so plugged-in charging can be indicated) ---
    # (MSK12C02 contacts are 50mA-rated: switch the EN signal, not the
    # battery current; SPDT gives clean VBATT/GND levels both positions.)
    # SW2's common is now SW_ON (VBATT on / GND off), no longer wired
    # straight to EN — D2 (BAT54S, two Schottkys in SERIES: 1=A1, 2=K2,
    # 3=K1+A2 midpoint, Nexperia ds Table 2) sits between:
    #   diode 1 (SW_ON -> PWR_EN): the switch still enables the LDO
    #     (EN = VBATT - ~0.2V, far above the 1.05V max rising threshold);
    #   diode 2 (PWR_EN -> VBATT): clamps EN to VBATT + Vf. Required:
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
    c.add("SW2", "slide_switch", "PWR", {1: "VBATT", 2: "SW_ON", 3: "GND"})
    c.add("D2", "or_diode", "BAT54S", {1: "SW_ON", 2: "VBATT", 3: "PWR_EN"})
    c.add("R17", "r_100k", "100k", {1: "PWR_EN", 2: "GND"})
    c.add("R18", "r_100k", "100k", {1: "VBUS", 2: "PWR_EN"})

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
    c.add("U4", "load_switch", "TPS22913", {
        "A2": "VSYS", "A1": "VLED", "B1": "GND", "B2": "LED_EN",
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
    c.add("Q3", "lvl_nfet", "BSS138W", {1: "LED_DATA", 2: "GND", 3: "LED_D0"})
    c.add("R23", "r_1k", "1k", {1: "VLED", 2: "LED_D0"})

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
