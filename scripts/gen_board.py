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

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "earring.kicad_pcb"
LIB = str(ROOT / "library" / "parts.pretty")

CENTER = (100.0, 100.0)  # board center in sheet coords, mm


def mm(v):
    return pcbnew.FromMM(v)


def setup_rules(board, design):
    j = design["jlcpcb"]
    bds = board.GetDesignSettings()
    bds.m_TrackMinWidth = mm(j["min_track_mm"])
    bds.m_ViasMinSize = mm(j["via_diameter_mm"])
    bds.m_MinThroughDrill = mm(j["via_drill_mm"])
    bds.m_MinClearance = mm(j["min_clearance_mm"])
    bds.m_HoleClearance = mm(0.15)  # freerouting only honors net clearance;\n    # its 0.127 spacing to the shell slots yields ~0.18 hole-copper
    bds.m_ViasMinAnnularWidth = mm(0.05)  # USB shell slot pads are 0.05
    # 0.1: the USB shell pads and side-button pads legitimately live at the
    # edge (connector overhangs); JLC tolerates this.
    bds.m_CopperEdgeClearance = mm(0.1)
    ns = bds.m_NetSettings
    default = ns.GetDefaultNetclass()
    default.SetTrackWidth(mm(j["default_track_mm"]))
    default.SetClearance(mm(j["min_clearance_mm"]))
    default.SetViaDiameter(mm(j["via_diameter_mm"]))
    default.SetViaDrill(mm(j["via_drill_mm"]))


def main():
    design = load_design()
    cir = build_circuit(design)
    OUT.parent.mkdir(exist_ok=True)
    if OUT.exists():
        OUT.unlink()
    board = pcbnew.NewBoard(str(OUT))
    board.SetCopperLayerCount(design["board"]["layers"])
    setup_rules(board, design)

    # --- outline ---
    r = design["board"]["diameter_mm"] / 2
    circle = pcbnew.PCB_SHAPE(board)
    circle.SetShape(pcbnew.SHAPE_T_CIRCLE)
    circle.SetCenter(pcbnew.VECTOR2I(mm(CENTER[0]), mm(CENTER[1])))
    circle.SetEnd(pcbnew.VECTOR2I(mm(CENTER[0] + r), mm(CENTER[1])))
    circle.SetLayer(pcbnew.Edge_Cuts)
    circle.SetWidth(mm(0.1))
    board.Add(circle)

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
    print(f"wrote {OUT}: {len(cir.components)} footprints, {len(nets)} nets")


if __name__ == "__main__":
    main()
