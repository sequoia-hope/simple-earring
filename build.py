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
STAGES = ["board", "place", "preview", "route", "finish", "drc", "render",
          "schematic", "export"]
SCRIPTS = {
    "board": "gen_board.py",
    "place": "place.py",
    "preview": "render.py --placement",   # unrouted render, before routing
    "route": "route.py",
    "finish": "finish.py",
    "drc": "drc.py",
    "render": "render.py",
    "schematic": "gen_schematic.py",
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
    ap.add_argument("--only", choices=STAGES, help="run a single stage")
    args = ap.parse_args()

    if args.only:
        stages = [args.only]
    elif args.to:
        stages = STAGES[: STAGES.index(args.to) + 1]
    else:
        stages = STAGES

    i = 0
    while i < len(stages):
        s = stages[i]
        # route+finish are a retry unit: freerouting is seed-dependent, so
        # a failed finish re-rolls the routing (up to 4 attempts)
        if s == "route" and i + 1 < len(stages) and stages[i + 1] == "finish":
            # Drop any best-attempt snapshot from an earlier run: it was
            # scored against a different netlist, and a stale one would
            # silently veto this run's real best.
            for stale in ("earring-best.kicad_pcb", "earring-best.json"):
                (ROOT / "out" / stale).unlink(missing_ok=True)
            done = False
            for attempt in range(6):
                if not run_stage("route"):
                    print("\nBuild stopped at stage 'route'.")
                    sys.exit(1)
                if run_stage("finish"):
                    done = True
                    break
                print(f"--- route/finish attempt {attempt + 1} incomplete; retrying ---")
            if not done:
                print("\nBuild stopped: route/finish did not converge.")
                sys.exit(1)
            i += 2
            continue
        if not run_stage(s):
            print(f"\nBuild stopped at stage '{s}'.")
            sys.exit(1)
        i += 1
    print("\nBuild complete.")


if __name__ == "__main__":
    main()
