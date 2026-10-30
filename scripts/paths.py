"""Where the pipeline's files live.

The KiCad project sits where the Boardroom suite looks for boards,
hw/<board>/<variant>/<board>.kicad_*, so Boardroom, Circuit Composer and
UltraRoute Studio all open it in place. Build products — renders, the
dashboard, DRC report, DSN/SES, fab files — stay in out/, which is what
`proj` serves.

KiCad paths inside the project (fp-lib-table, footprint 3D models) are
${KIPRJMOD}-relative, so they climb three levels: ${KIPRJMOD}/../../../library.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARD = "earring"
VARIANT = "a"
HW = ROOT / "hw" / BOARD / VARIANT
PCB = HW / f"{BOARD}.kicad_pcb"
PRO = HW / f"{BOARD}.kicad_pro"
DRU = HW / f"{BOARD}.kicad_dru"
SCH = HW / f"{BOARD}.kicad_sch"
OUT = ROOT / "out"
# what ${KIPRJMOD} must prepend to reach ROOT
PRJ_TO_ROOT = "${KIPRJMOD}/../../.."
