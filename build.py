#!/usr/bin/env python3
"""Build orchestrator: runs pipeline stages in order.

Usage:
  python3 build.py                 # all stages
  python3 build.py --to route      # stop after 'route'
  python3 build.py --only render   # run a single stage
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
STAGES = ["board", "place", "preview", "route", "drc", "render",
          "schematic", "compose", "export"]
SCRIPTS = {
    "board": "gen_board.py",
    "place": "place.py",
    "preview": "render.py --placement",   # unrouted render, before routing
    "route": "route.py",                # pre-routes, pours, then ultraroute
    "finish": "finish.py",  # freerouting-era repair loop; --only finish
    "drc": "drc.py",
    "render": "render.py",
    "schematic": "gen_schematic.py",
    "compose": "export_compose.py",  # compose/earring/ for Circuit Composer
    "export": "export.py",
}


def run_stage(name: str) -> bool:
    parts = SCRIPTS[name].split()
    script = ROOT / "scripts" / parts[0]
    if not script.exists():
        print(f"[{name}] SKIP — {script.name} not written yet")
        return True
    print(f"\n=== [{name}] {SCRIPTS[name]} ===")
    t0 = time.time()
    r = subprocess.run([sys.executable, str(script)] + parts[1:], cwd=ROOT)
    dt = time.time() - t0
    status = "ok" if r.returncode == 0 else f"FAILED ({r.returncode})"
    print(f"=== [{name}] {status} in {dt:.1f}s ===")
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", choices=STAGES, help="stop after this stage")
    ap.add_argument("--only", choices=list(SCRIPTS), help="run a single stage")
    args = ap.parse_args()

    if args.only:
        stages = [args.only]
    elif args.to:
        stages = STAGES[: STAGES.index(args.to) + 1]
    else:
        stages = STAGES

    for s in stages:
        if not run_stage(s):
            print(f"\nBuild stopped at stage '{s}'.")
            sys.exit(1)
    print("\nBuild complete.")


if __name__ == "__main__":
    main()
