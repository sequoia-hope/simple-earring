"""Review F2 margin study (python3 design/sim/button/leakstudy.py, ~1 min, 4 threads): board off at 85C. Off-state EN vs (Q4 VGS(th) tempco, extra
leak on LATCH_G such as Q5 IDSS) for candidate fixes. LDO held off (en_th=10)
so the leak is measured, not acted on."""
import sys, subprocess, itertools
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run
OUT = run.OUT / "leak"
OUT.mkdir(parents=True, exist_ok=True)
ng = run.ngspice_bin(None)

def r24(v):
    def f(c):
        c.components["R24"].value = v
        return c
    return f
def cj(c):
    c.components["Q4"].part = "oring_pfet"
    return c
run.VARIANTS.update({"cj2101": cj, "cj2101_22k": lambda c: r24("22k")(cj(c))})
scn = run.Scenario("leak", "", 0.3, tstep=100e-6)
cands = {  # name -> (variant, Q4 part threshold param, |Vth|min at 25C)
    "Q4 CJ2101 (pre-F2), R24 100k": ("cj2101", "vto_p", 0.45),
    "Q4 CJ2101, R24 22k": ("cj2101_22k", "vto_p", 0.45),
    "Q4 LBSS84WT1G (board)": ("board", "vto_p4", 0.80)}
tcs = [-2e-3, -3e-3, -4e-3]
leaks = [0, 1e-6, 3e-6]
jobs = list(itertools.product(cands, tcs, leaks))

def one(job):
    name, tc, lk = job
    var, key, vth = cands[name]
    ov = {"en_th": 10, key: -(vth + tc * 60), "idss": 0, "tag": f"{abs(hash(job))}"}
    scn2 = run.Scenario("leak", "", 0.3, tstep=100e-6,
                        extra=[f"Bq5leak LATCH_G 0 I = {lk:g} * tanh(V(LATCH_G)/0.2)"])
    raw, net, p, probes = run.tb(scn2, var, "hot", "4.2", ov)
    cir = OUT / f"{raw}.cir"
    net = net.replace(str(run.OUT / "data"), str(OUT))
    cir.write_text(net)
    subprocess.run([ng, "-b", str(cir)], capture_output=True, timeout=600)
    dat = OUT / f"{raw}.txt"
    arr = np.loadtxt(dat, skiprows=1)
    hdr = [h[2:-1].upper() if h.startswith("v(") else h for h in dat.read_text().split("\n", 1)[0].split()]
    last = dict(zip(hdr, arr[-1]))
    return name, tc, lk, last["PWR_EN"], last["LATCH_G"] - last["VBATT"]

with ThreadPoolExecutor(4) as ex:
    rows = list(ex.map(one, jobs))
print("EN (V) at 85C, board off, cell 4.2V; self-start if >= 0.7 (NCP730 min)")
print(f"{'candidate':26s} {'tempco':>7s} " + "  ".join(f"leak {l*1e6:.0f}uA" for l in leaks))
for name in cands:
    for tc in tcs:
        r = [x for x in rows if x[0] == name and x[1] == tc]
        r.sort(key=lambda x: x[2])
        print(f"{name:26s} {tc*1e3:5.0f}mV " + "  ".join(f"{x[3]:9.2f}" for x in r))
