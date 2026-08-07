#!/usr/bin/env python3
"""Generate a fresh 4-layer .kicad_pcb from circuit.py + design.yaml.

Creates board outline, nets, footprints (at origin — place.py positions them),
and JLCPCB design rules. Output: out/earring.kicad_pcb (fully regenerated).
"""
import sys
from pathlib import Path

import pcbnew

sys.path.insert(0, str(Path(__file__).resolve().parent))
from circuit import build_circuit, load_design  # noqa: E402
from gen_schematic import FP_LIB, SHEET_UUID, uid  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "earring.kicad_pcb"
LIB = str(ROOT / "library" / "parts.pretty")

CENTER = (100.0, 100.0)  # board center in sheet coords, mm


def mm(v):
    return pcbnew.FromMM(v)


def write_fp_lib_table():
    """Register library/parts.pretty so the schematic's "earring:<fp>"
    footprint references resolve. KiCad looks for this next to the
    project file, which lives in out/."""
    (OUT.parent / "fp-lib-table").write_text(
        "(fp_lib_table\n  (version 7)\n"
        f'  (lib (name "{FP_LIB}")(type "KiCad")'
        '(uri "${KIPRJMOD}/../library/parts.pretty")'
        '(options "")(descr "simple_earring generated footprints"))\n)\n')


def link_to_schematic(fp, ref):
    """Stamp the library nickname and the schematic symbol's UUID path.

    "Update PCB from Schematic" matches footprints to symbols by this
    path; without it KiCad can't tell that board R10 IS schematic R10.
    gen_schematic.py derives its UUIDs deterministically, so both sides
    compute the same value without either having to run first."""
    fp.SetFPID(pcbnew.LIB_ID(FP_LIB, fp.GetFPID().GetLibItemName()))
    fp.SetPath(pcbnew.KIID_PATH(f"/{SHEET_UUID}/{uid('sym', ref)}"))


def setup_rules(board, design):
    j = design["jlcpcb"]
    bds = board.GetDesignSettings()
    bds.m_TrackMinWidth = mm(j["min_track_mm"])
    bds.m_ViasMinSize = mm(j["via_diameter_mm"])
    bds.m_MinThroughDrill = mm(j["via_drill_mm"])
    bds.m_MinClearance = mm(j["min_clearance_mm"])
    # JLC 4-layer limits (capabilities page, checked 2026-08-07). Freerouting
    # only honors net clearance, so a fresh auto-route can land ~0.18mm
    # hole-to-copper at the USB shell slots — DRC will catch it; nudge by hand.
    # PTH-specific tighter limits (0.28 hole-copper, 0.45 hole-hole) live in
    # out/earring.kicad_dru.
    bds.m_HoleClearance = mm(0.2)
    bds.m_HoleToHoleMin = mm(0.2)
    bds.m_ViasMinAnnularWidth = mm(0.05)  # JLC via min; USB shell slots are 0.05
    bds.m_CopperEdgeClearance = mm(0.2)
    bds.m_SolderMaskMinWidth = mm(0.1)  # JLC min mask dam
    ns = bds.m_NetSettings
    default = ns.GetDefaultNetclass()
    default.SetTrackWidth(mm(j["default_track_mm"]))
    default.SetClearance(mm(j["min_clearance_mm"]))
    default.SetViaDiameter(mm(j["via_diameter_mm"]))
    default.SetViaDrill(mm(j["via_drill_mm"]))
    # "power" class: fat VBUS (Sequoia hand-routed it 0.4mm on In3; the
    # netclass width flows into the freerouting DSN so generated builds
    # keep it). VBATT/VLED/3V3 stay default — they feed from planes.
    power = pcbnew.NETCLASS("power")
    power.SetTrackWidth(mm(j["power_track_mm"]))
    power.SetClearance(mm(j["min_clearance_mm"]))
    power.SetViaDiameter(mm(j["via_diameter_mm"]))
    power.SetViaDrill(mm(j["via_drill_mm"]))
    ns.SetNetclass("power", power)
    ns.SetNetclassPatternAssignment("VBUS", "power")
    # "usb" class: same geometry as default, but carries diff-pair
    # width/gap so KiCad's interactive router pairs USB_C_DP/USB_C_DN
    # (trailing-p/n names) when hand-finishing. Freerouting ignores it;
    # the locked pre-routes in route.py do the pairing for generated
    # builds. Gap 0.25 = the 0.40mm centers Sequoia used minus width.
    usb = pcbnew.NETCLASS("usb")
    usb.SetTrackWidth(mm(j["default_track_mm"]))
    usb.SetClearance(mm(j["min_clearance_mm"]))
    usb.SetViaDiameter(mm(j["via_diameter_mm"]))
    usb.SetViaDrill(mm(j["via_drill_mm"]))
    usb.SetDiffPairWidth(mm(j["default_track_mm"]))
    usb.SetDiffPairGap(mm(0.25))
    usb.SetDiffPairViaGap(mm(0.25))
    ns.SetNetclass("usb", usb)
    ns.SetNetclassPatternAssignment("USB_C_D*", "usb")


def main():
    design = load_design()
    cir = build_circuit(design)
    OUT.parent.mkdir(exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    board = pcbnew.NewBoard(str(OUT))
    board.SetCopperLayerCount(design["board"]["layers"])
    setup_rules(board, design)

    # --- outline: teardrop (arc + two tangents + truncated tip) ---
    import math
    from outline import geometry
    og = geometry(design)

    def V(x, y):
        return pcbnew.VECTOR2I(mm(CENTER[0] + x), mm(CENTER[1] + y))

    arc = pcbnew.PCB_SHAPE(board)
    arc.SetShape(pcbnew.SHAPE_T_ARC)
    a0, a1 = og["ang_r"], og["ang_l"]
    while a1 < a0:
        a1 += 2 * math.pi
    amid = (a0 + a1) / 2
    R = og["R"]
    arc.SetArcGeometry(V(*og["tang_r"]),
                       V(R * math.cos(amid), R * math.sin(amid)),
                       V(*og["tang_l"]))
    arc.SetLayer(pcbnew.Edge_Cuts)
    arc.SetWidth(mm(0.1))
    board.Add(arc)
    for p0, p1 in ((og["tang_l"], og["corner_l"]),
                   (og["corner_l"], og["corner_r"]),
                   (og["corner_r"], og["tang_r"])):
        ln = pcbnew.PCB_SHAPE(board)
        ln.SetShape(pcbnew.SHAPE_T_SEGMENT)
        ln.SetStart(V(*p0))
        ln.SetEnd(V(*p1))
        ln.SetLayer(pcbnew.Edge_Cuts)
        ln.SetWidth(mm(0.1))
        board.Add(ln)

    # --- nets ---
    nets = {}
    for name in sorted(cir.nets):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni

    # --- footprints ---
    missing = []
    for ref, comp in cir.components.items():
        fp = pcbnew.FootprintLoad(LIB, comp.footprint)
        if fp is None:
            missing.append((ref, comp.footprint))
            continue
        fp.SetReference(ref)
        fp.SetValue(comp.value)
        link_to_schematic(fp, ref)
        fp.SetField("LCSC", comp.lcsc or "")
        for field in fp.GetFields():
            if field.GetName() in ("LCSC", "Value"):
                field.SetVisible(False)
        fp.SetPosition(pcbnew.VECTOR2I(mm(CENTER[0]), mm(CENTER[1])))
        for pad in fp.Pads():
            net = comp.pins.get(pad.GetNumber(), "")
            if net:
                pad.SetNet(nets[net])

        board.Add(fp)

    if missing:
        for ref, f in missing:
            print(f"ERROR: footprint not found: {ref} -> {f}")
        sys.exit(1)

    pcbnew.SaveBoard(str(OUT), board)
    write_fp_lib_table()
    print(f"wrote {OUT}: {len(cir.components)} footprints, {len(nets)} nets")


if __name__ == "__main__":
    main()
