#!/usr/bin/env python3
"""Shaded orthographic previews of the TPU case STLs (numpy z-buffer).

    python3 scripts/preview_case.py          # -> out/case/preview/*.png + index.html

Runs on the system python (numpy only) — no CAD kernel needed.
"""
import math
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "out" / "case"
PREV = CASE / "preview"
W = H = 760


def load_stl(path):
    b = path.read_bytes()
    n = struct.unpack("<I", b[80:84])[0]
    if 84 + n * 50 != len(b):
        raise ValueError(f"{path}: not a binary STL")
    a = np.frombuffer(b[84:], dtype=np.uint8).reshape(n, 50)
    f = a[:, :48].copy().view("<f4").reshape(n, 4, 3)
    return f[:, 1:, :].astype(np.float64)


def render(tris_list, colors, elev, azim, size=(W, H), light=(-0.4, -0.5, 0.85),
           bg=250, clip=None):
    """Orthographic z-buffer render.  tris_list: list of (M,3,3) arrays."""
    if clip is not None:                       # model-space half-space cut
        ax, lim, keep_above = clip
        cut = []
        for t in tris_list:
            m = (t[:, :, ax] > lim) if keep_above else (t[:, :, ax] < lim)
            cut.append(t[m.all(axis=1)])
        tris_list = cut
    ez, az = math.radians(elev), math.radians(azim)
    Rz = np.array([[math.cos(az), -math.sin(az), 0],
                   [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(ez), -math.sin(ez)],
                   [0, math.sin(ez), math.cos(ez)]])
    M = Rx @ Rz
    allv = np.concatenate([t.reshape(-1, 3) for t in tris_list])
    ctr = (allv.min(0) + allv.max(0)) / 2
    view = [(t - ctr) @ M.T for t in tris_list]
    pv = np.concatenate([v.reshape(-1, 3) for v in view])
    span = max(np.ptp(pv[:, 0]), np.ptp(pv[:, 1])) * 1.08
    sc = min(size) / span
    ox, oy = size[0] / 2, size[1] / 2

    img = np.full((size[1], size[0], 3), bg, dtype=np.float64)
    zbuf = np.full((size[1], size[0]), -1e9)
    L = np.array(light, dtype=float)
    L /= np.linalg.norm(L)

    for v, col in zip(view, colors):
        if len(v) == 0:
            continue
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        ln = np.linalg.norm(n, axis=1)
        ok = ln > 1e-12
        v, n, ln = v[ok], n[ok], ln[ok]
        n = n / ln[:, None]
        v = v[n[:, 2] > 0]                       # backface cull
        nn = n[n[:, 2] > 0]
        sh = np.clip(nn @ L, 0, 1) * 0.72 + 0.28
        x = v[:, :, 0] * sc + ox
        y = -v[:, :, 1] * sc + oy
        z = v[:, :, 2]
        col = np.array(col, dtype=float)
        for i in range(len(v)):
            xi, yi, zi = x[i], y[i], z[i]
            x0 = max(int(math.floor(xi.min())), 0)
            x1 = min(int(math.ceil(xi.max())) + 1, size[0])
            y0 = max(int(math.floor(yi.min())), 0)
            y1 = min(int(math.ceil(yi.max())) + 1, size[1])
            if x1 <= x0 or y1 <= y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
            d = ((yi[1] - yi[2]) * (xi[0] - xi[2]) + (xi[2] - xi[1]) * (yi[0] - yi[2]))
            if abs(d) < 1e-12:
                continue
            l0 = ((yi[1] - yi[2]) * (gx - xi[2]) + (xi[2] - xi[1]) * (gy - yi[2])) / d
            l1 = ((yi[2] - yi[0]) * (gx - xi[2]) + (xi[0] - xi[2]) * (gy - yi[2])) / d
            l2 = 1 - l0 - l1
            m = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
            if not m.any():
                continue
            zz = l0 * zi[0] + l1 * zi[1] + l2 * zi[2]
            sub = zbuf[y0:y1, x0:x1]
            upd = m & (zz > sub)
            sub[upd] = zz[upd]
            img[y0:y1, x0:x1][upd] = col * sh[i]
    return np.clip(img, 0, 255).astype(np.uint8)


def write_png(path, arr):
    import zlib
    h, w, _ = arr.shape
    raw = b"".join(b"\x00" + arr[i].tobytes() for i in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
    path.write_bytes(png)


def printability(tris, bed_normal):
    """Report unsupported overhangs for a part printed with the face whose
    outward normal is `bed_normal` (model space) flat on the bed."""
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    a2 = np.linalg.norm(n, axis=1)
    ok = a2 > 1e-12
    n, a2, t = n[ok] / a2[ok, None], a2[ok] / 2, tris[ok]
    bn = np.array(bed_normal, dtype=float)
    down = n @ bn                    # >0 => faces the bed => needs support
    z = (t @ bn).mean(axis=1)
    zbed = z.max()
    slope = np.degrees(np.arccos(np.clip(np.abs(down), 0, 1)))   # 0 = horizontal
    bed = (down > 0.999) & (z > zbed - 1e-3)
    bad = (down > 0.02) & (slope < 45.0) & ~bed
    by_h = {}
    for h, a in zip(np.round(zbed - z[bad], 2), a2[bad]):
        by_h[h] = by_h.get(h, 0.0) + a
    return dict(bed_area=a2[bed].sum(), total=a2.sum(),
                overhang_area=a2[bad].sum(),
                worst=float(slope[bad].min()) if bad.any() else 90.0,
                worst_h=float(zbed - z[bad][np.argmin(slope[bad])]) if bad.any() else 0.0,
                by_h=sorted(by_h.items(), key=lambda kv: -kv[1])[:5])


TPU_F = (232, 236, 242)
TPU_R = (168, 178, 194)
PCB = (46, 78, 56)
PARTS = (214, 148, 74)


def main():
    PREV.mkdir(parents=True, exist_ok=True)
    front = load_stl(CASE / "earring-case-front.stl")
    rear = load_stl(CASE / "earring-case-rear.stl")
    board = load_stl(CASE / "board-stub.stl")
    comps = load_stl(CASE / "parts-stub.stl")

    # tilt = angle off the +z axis: 0 looks straight down onto the front face,
    # 180 looks at the back.  clip = (axis, limit, keep_above) in model space.
    shots = [
        ("front-outer", [front], [TPU_F], 0, 0, None),
        ("front-inner", [front], [TPU_F], 180, 0, None),
        ("front-inner-iso", [front], [TPU_F], 150, 22, None),
        ("rear-outer", [rear], [TPU_R], 180, 0, None),
        ("rear-inner", [rear], [TPU_R], 0, 0, None),
        ("rear-inner-iso", [rear], [TPU_R], 32, -22, None),
    ]
    full = [front, rear, board, comps]
    cols = [TPU_F, TPU_R, PCB, PARTS]
    shots += [
        ("assembly-front", full, cols, 0, 0, None),
        ("assembly-rear", full, cols, 180, 0, None),
        ("assembly-iso", full, cols, 36, 20, None),
        ("assembly-tip-usb", full, cols, 74, 0, None),
        ("assembly-edge", full, cols, 90, 0, None),
        ("assembly-edge-sw2", full, cols, 90, -55, None),
        ("assembly-scoop-iso", full, cols, 66, -48, None),
    ]
    for tag, tilt, az in (("y", 90, 0), ("x", 90, 90)):
        sec = [load_stl(CASE / f"sec{tag}-{n}.stl")
               for n in ("front", "rear", "board", "parts")]
        shots.append((f"section-{tag}", sec, cols, tilt, az, None))
        shots.append((f"section-{tag}-iso", sec, cols, tilt - 22, az + 16, None))
    # printed outer-face-down: the front's outer face is +z, the rear's is -z
    lines = []
    for nm, tris, bn in (("front", front, (0, 0, 1)), ("rear", rear, (0, 0, -1))):
        r = printability(tris, bn)
        lines.append(f"{nm}: bed contact {r['bed_area']:.0f} mm2, "
                     f"unsupported overhang {r['overhang_area']:.2f} mm2"
                     + (f" (worst {r['worst']:.0f} deg from horizontal, "
                        f"{r['worst_h']:.2f} mm off the bed)"
                        if r["overhang_area"] else ""))
        if r["by_h"]:
            lines.append("        by height off the bed: " + ", ".join(
                f"{h:.2f} mm: {a:.1f} mm2" for h, a in r["by_h"]))
    print("\n".join("  " + s for s in lines))
    (PREV / "printability.txt").write_text("\n".join(lines) + "\n")

    names = []
    for name, tl, cols, elev, azim, clip in shots:
        img = render(tl, cols, elev, azim, clip=clip)
        write_png(PREV / f"{name}.png", img)
        names.append(name)
        print("wrote", name)

    cards = "\n".join(
        f'<figure><img src="{n}.png" alt="{n}"><figcaption>{n}</figcaption></figure>'
        for n in names)
    rpt = (CASE / "report.txt")
    rpt = rpt.read_text() if rpt.exists() else ""
    (PREV / "index.html").write_text(f"""<!doctype html><meta charset=utf-8>
<title>simple_earring TPU case</title>
<style>
 body{{background:#14161a;color:#dfe3ea;font:14px/1.5 system-ui,sans-serif;margin:24px}}
 h1{{font-size:18px;font-weight:600;margin:0 0 4px}}
 h2{{font-size:14px;font-weight:600;color:#9fb0c8;margin:26px 0 10px}}
 p.sub{{color:#8b95a6;margin:0 0 18px}}
 .g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:18px}}
 figure{{margin:0;background:#1d2027;border-radius:10px;padding:10px}}
 img{{width:100%;display:block;border-radius:6px}}
 figcaption{{padding-top:8px;color:#97a0b0;font-size:12px}}
 pre{{background:#1d2027;border-radius:10px;padding:14px 16px;overflow-x:auto;
      font:12px/1.6 ui-monospace,monospace;color:#c6d0de}}
 a{{color:#79b8ff}}
</style>
<h1>simple_earring — TPU clip-on case</h1>
<p class=sub>front = LED diffuser &middot; rear = battery cup &middot; alternating
 clip stations &middot; STEP + STL in <a href="../">out/case/</a></p>
<div class=g>{cards}</div>
<h2>fit &amp; build report</h2><pre>{rpt}</pre>
<h2>printability (printed outer-face-down)</h2><pre>{chr(10).join(lines)}</pre>
""")
    print("open", PREV / "index.html")


if __name__ == "__main__":
    sys.exit(main())
