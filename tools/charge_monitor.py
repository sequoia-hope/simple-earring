#!/usr/bin/env python3
"""charge_monitor.py — live charge status for the simple_earring board.

Autoconnects to whichever port the RP2350 shows up on (USB VID 0x2E8A),
parses the firmware's status lines, and plots VBATT against the two
voltages that actually matter on this board:

  3.70 V  SK6805-EC10 minimum VDD (bom/parts.yaml:41). VLED is VBATT
          through the TPS22913 (circuit.py:361), so BELOW THIS THE LED
          RING CANNOT LIGHT AT ALL — no firmware change helps. This is
          the line to watch; the cell has historically lived under it.
  4.20 V  LIR2032 full.

Because there is no power path (the NCP730's IN and the LGS4056H's BAT
are the same VBATT node — circuit.py:325 / :280), the ~41 mA program
current is shared with the running MCU and the climb is slow. The rate
and ETA readouts exist to tell you whether the cell is actually gaining
and when it will clear the 3.70 V line.

READ-ONLY: this never writes a byte to the port. The firmware's command
handler takes 'X' (wipe old sessions), so an app that echoed stray input
could destroy wear logs. It only ever reads.

Usage:
    python3 tools/charge_monitor.py                 # autoconnect
    python3 tools/charge_monitor.py --port /dev/ttyACM0
    python3 tools/charge_monitor.py --csv charge.csv

Needs only the stdlib plus pyserial.
"""
from __future__ import annotations

import argparse
import queue
import re
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from collections import deque

import serial
import serial.tools.list_ports

RP_VID = 0x2E8A  # Raspberry Pi; the sketch enumerates as 2e8a:f00f
BAUD = 115200

LED_FLOOR_MV = 3700  # SK6805-EC10 VDD min — below this the ring is dark
FULL_MV = 4200       # LIR2032 full
EMPTY_MV = 3000      # LIR2032 floor; gauge left edge

RATE_WINDOW_S = 600    # least-squares window for mV/min
RATE_MIN_SPAN_S = 45   # ...and the minimum span before we trust a slope
RATE_MIN_POINTS = 6
CHART_WINDOW_S = 900
HISTORY_MAX = 40000

# The firmware prints VBATT on two different lines: measureCharge()'s
#   level chrg=1 done=0 vbatt=3568mV pct=3
# and runShowFrame()'s status line
#   drops=.. jolt=.. ... vbatt=3568mV chrg=0 done=0 ep=..s log=..B
# Pull the fields out wherever they appear so the app works in show mode
# too, not just while charging.
RE_VBATT = re.compile(r"vbatt=(-?\d+)mV")
RE_CHRG = re.compile(r"\bchrg=(\d)")
RE_DONE = re.compile(r"\bdone=(\d)")
RE_PCT = re.compile(r"\bpct=(-?\d+)")

BG = "#12141a"
FG = "#e6e9ef"
DIM = "#78808f"
ACCENT = "#5ac8fa"
GOOD = "#4ade80"
WARN = "#fbbf24"
BAD = "#f87171"
GRID = "#242832"


def chargePct(mv: int, charging: bool) -> float:
    """Mirror of chargePct() in firmware/src/main.cpp:251.

    Used only when a line carries vbatt but no pct (i.e. show mode); the
    firmware's own pct is preferred whenever it is present so the app
    never disagrees with the board about its own gauge.
    """
    if charging:
        mv -= 150
    v = [3300, 3600, 3750, 3850, 3950, 4050, 4150, 4200]
    p = [0.0, 8.0, 25.0, 45.0, 62.0, 78.0, 92.0, 100.0]
    if mv <= v[0]:
        return 0.0
    for i in range(1, 8):
        if mv <= v[i]:
            return p[i - 1] + (p[i] - p[i - 1]) * (mv - v[i - 1]) / (v[i] - v[i - 1])
    return 100.0


def find_board(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit
    cand = [p for p in serial.tools.list_ports.comports() if p.vid == RP_VID]
    # f00f is the running sketch's CDC; prefer it over anything else the
    # chip might be enumerating as (e.g. a second interface).
    cand.sort(key=lambda p: 0 if p.pid == 0xF00F else 1)
    return cand[0].device if cand else None


class Reader(threading.Thread):
    """Serial reader: owns the port, reconnects forever, never writes."""

    def __init__(self, q: queue.Queue, port: str | None):
        super().__init__(daemon=True)
        self.q = q
        self.port = port
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            dev = find_board(self.port)
            if not dev:
                self.q.put(("state", "searching", None))
                self._stop.wait(1.0)
                continue
            try:
                # exclusive=True matters: without it Linux happily lets a
                # second reader open the same ttyACM, and the two then
                # SPLIT the line stream between them — each sees a random
                # half of the samples and neither reports an error. For a
                # diagnostic tool, refusing to start is far better than
                # quietly showing a gappy graph next to a stray monitor.
                # (POSIX-only kwarg; fall back if the platform rejects it.)
                try:
                    ser = serial.Serial(dev, BAUD, timeout=1, exclusive=True)
                except TypeError:
                    ser = serial.Serial(dev, BAUD, timeout=1)
            except (serial.SerialException, OSError) as e:
                # Busy is the common one: another capture holds the port.
                self.q.put(("state", f"{dev} busy — another monitor has it?", None))
                self._stop.wait(1.0)
                continue
            self.q.put(("state", "connected", dev))
            try:
                with ser:
                    while not self._stop.is_set():
                        raw = ser.readline()
                        if raw:
                            self.q.put(("line", raw.decode("utf-8", "replace").strip(),
                                        time.time()))
            except (serial.SerialException, OSError):
                pass  # unplugged mid-read; fall through and rescan
            self.q.put(("state", "lost", dev))


def lsq_slope(pts) -> float | None:
    """mV per second over pts=[(t, mv)], or None if not enough signal."""
    if len(pts) < RATE_MIN_POINTS:
        return None
    if pts[-1][0] - pts[0][0] < RATE_MIN_SPAN_S:
        return None
    n = len(pts)
    mt = sum(p[0] for p in pts) / n
    mv = sum(p[1] for p in pts) / n
    den = sum((p[0] - mt) ** 2 for p in pts)
    if den <= 0:
        return None
    return sum((p[0] - mt) * (p[1] - mv) for p in pts) / den


def fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds > 48 * 3600:
        return "—"
    m = int(seconds // 60)
    if m < 60:
        return f"{m} min"
    return f"{m // 60} h {m % 60:02d} m"


class App:
    def __init__(self, root: tk.Tk, args):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.hist: deque = deque(maxlen=HISTORY_MAX)  # (t, mv)
        self.t0 = time.time()
        self.conn = "searching"
        self.dev = ""
        self.mv = None
        self.chrg = False
        self.done = False
        self.pct = None
        self.pct_src = ""
        self.last_rx = 0.0
        self.csv = open(args.csv, "a", buffering=1) if args.csv else None
        if self.csv and self.csv.tell() == 0:
            self.csv.write("unix_t,vbatt_mv,chrg,done,pct\n")

        root.title("simple_earring — charge monitor")
        root.configure(bg=BG)
        root.minsize(460, 560)

        mono = "DejaVu Sans Mono"
        if mono not in tkfont.families():
            mono = "TkFixedFont"
        self.f_big = (mono, 44, "bold")
        self.f_mid = (mono, 13)
        self.f_small = (mono, 10)

        pad = dict(bg=BG, fg=FG)

        # --- header: connection state -------------------------------
        head = tk.Frame(root, bg=BG)
        head.pack(fill="x", padx=14, pady=(12, 4))
        self.dot = tk.Canvas(head, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot.pack(side="left", pady=2)
        self.dot_id = self.dot.create_oval(2, 2, 11, 11, fill=BAD, outline="")
        self.l_conn = tk.Label(head, text="searching…", font=self.f_small,
                               bg=BG, fg=DIM, anchor="w")
        self.l_conn.pack(side="left", padx=(8, 0))

        # --- the number ---------------------------------------------
        self.l_volt = tk.Label(root, text="—.——  V", font=self.f_big, **pad)
        self.l_volt.pack(pady=(10, 0))
        self.l_state = tk.Label(root, text="no data", font=self.f_mid, bg=BG, fg=DIM)
        self.l_state.pack(pady=(2, 10))

        # --- gauge ---------------------------------------------------
        self.gauge = tk.Canvas(root, height=76, bg=BG, highlightthickness=0)
        self.gauge.pack(fill="x", padx=14)
        self.gauge.bind("<Configure>", lambda e: self.draw_gauge())

        self.l_floor = tk.Label(root, text="", font=self.f_small, bg=BG, fg=DIM,
                                wraplength=520, justify="center")
        self.l_floor.pack(pady=(2, 10))

        # --- stats ---------------------------------------------------
        stats = tk.Frame(root, bg=BG)
        stats.pack(fill="x", padx=14)
        stats.columnconfigure(1, weight=1)
        self.l_rate = self._stat(stats, 0, "rate")
        self.l_eta_led = self._stat(stats, 1, "→ 3.70 V (lights)")
        self.l_eta_full = self._stat(stats, 2, "→ 4.20 V (full)")
        self.l_pct = self._stat(stats, 3, "gauge")

        # --- chart ---------------------------------------------------
        tk.Label(root, text="VBATT — last 15 min", font=self.f_small,
                 bg=BG, fg=DIM, anchor="w").pack(fill="x", padx=14, pady=(14, 2))
        self.chart = tk.Canvas(root, height=190, bg=BG, highlightthickness=1,
                               highlightbackground=GRID)
        self.chart.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.chart.bind("<Configure>", lambda e: self.draw_chart())

        self.reader = Reader(self.q, args.port)
        self.reader.start()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick()

    def _stat(self, parent, row, label):
        tk.Label(parent, text=label, font=self.f_small, bg=BG, fg=DIM,
                 anchor="w").grid(row=row, column=0, sticky="w", pady=2)
        v = tk.Label(parent, text="—", font=self.f_mid, bg=BG, fg=FG, anchor="e")
        v.grid(row=row, column=1, sticky="e", pady=2)
        return v

    # ---- data ------------------------------------------------------
    def feed(self, line: str, t: float):
        m = RE_VBATT.search(line)
        if not m:
            return
        mv = int(m.group(1))
        c = RE_CHRG.search(line)
        d = RE_DONE.search(line)
        p = RE_PCT.search(line)
        if c:
            self.chrg = c.group(1) == "1"
        if d:
            self.done = d.group(1) == "1"
        self.last_rx = t
        # vbatt <= 0 means senseOnce() could not decode (switch off
        # without the 2M off-throw mod) — keep it out of the history.
        if mv <= 0:
            self.mv = None
            return
        self.mv = mv
        if p:
            self.pct, self.pct_src = float(p.group(1)), "firmware"
        else:
            self.pct, self.pct_src = chargePct(mv, self.chrg), "local"
        self.hist.append((t, mv))
        if self.csv:
            self.csv.write(f"{t:.3f},{mv},{int(self.chrg)},{int(self.done)},"
                           f"{self.pct:.1f}\n")

    def tick(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "line":
                    self.feed(a, b)
                elif kind == "state":
                    if a == "connected":
                        self.conn, self.dev = "connected", b
                    elif a == "lost":
                        self.conn, self.dev = "lost", b
                    else:
                        self.conn, self.dev = a, ""
        except queue.Empty:
            pass
        self.refresh()
        self.root.after(150, self.tick)

    def rate_mv_s(self):
        if not self.hist:
            return None
        cut = self.hist[-1][0] - RATE_WINDOW_S
        return lsq_slope([p for p in self.hist if p[0] >= cut])

    # ---- rendering -------------------------------------------------
    def refresh(self):
        stale = self.last_rx and (time.time() - self.last_rx) > 12
        if self.conn == "connected" and not stale:
            self.dot.itemconfig(self.dot_id, fill=GOOD)
            self.l_conn.config(text=f"connected   {self.dev}", fg=DIM)
        elif self.conn == "connected" and stale:
            self.dot.itemconfig(self.dot_id, fill=WARN)
            self.l_conn.config(text=f"{self.dev} — no data for "
                                    f"{int(time.time() - self.last_rx)}s", fg=WARN)
        else:
            self.dot.itemconfig(self.dot_id, fill=BAD)
            txt = {"searching": "searching for board (USB 2e8a)…",
                   "lost": f"lost {self.dev} — reconnecting…"}.get(self.conn, self.conn)
            self.l_conn.config(text=txt, fg=DIM)

        if self.mv is None:
            self.l_volt.config(text="—.——  V", fg=DIM)
            self.l_state.config(text="no reading", fg=DIM)
            self.l_floor.config(text="")
        else:
            self.l_volt.config(text=f"{self.mv / 1000:.3f}  V",
                               fg=GOOD if self.mv >= LED_FLOOR_MV else WARN)
            if self.done:
                self.l_state.config(text="DONE — charge complete", fg=GOOD)
            elif self.chrg:
                self.l_state.config(text="CHARGING", fg=ACCENT)
            else:
                self.l_state.config(text="not charging", fg=DIM)
            gap = LED_FLOOR_MV - self.mv
            if gap > 0:
                self.l_floor.config(
                    text=f"LED ring DARK — {gap} mV below the SK6805 3.70 V floor.\n"
                         f"No firmware change can light it until this clears.", fg=BAD)
            else:
                self.l_floor.config(text="above the 3.70 V LED floor — ring can light",
                                    fg=GOOD)

        r = self.rate_mv_s()
        if r is None:
            self.l_rate.config(text="—", fg=DIM)
            self.l_eta_led.config(text="—", fg=DIM)
            self.l_eta_full.config(text="—", fg=DIM)
        else:
            per_min = r * 60
            self.l_rate.config(text=f"{per_min:+.1f} mV/min",
                               fg=GOOD if per_min > 0.2 else
                                  (BAD if per_min < -0.2 else DIM))
            if per_min > 0.2 and self.mv is not None:
                led = (LED_FLOOR_MV - self.mv) / r if self.mv < LED_FLOOR_MV else 0
                full = (FULL_MV - self.mv) / r if self.mv < FULL_MV else 0
                self.l_eta_led.config(
                    text="reached" if led == 0 else fmt_eta(led),
                    fg=GOOD if led == 0 else FG)
                self.l_eta_full.config(text="reached" if full == 0 else fmt_eta(full),
                                       fg=GOOD if full == 0 else FG)
            else:
                self.l_eta_led.config(text="not gaining", fg=BAD)
                self.l_eta_full.config(text="not gaining", fg=BAD)

        if self.pct is None:
            self.l_pct.config(text="—", fg=DIM)
        else:
            self.l_pct.config(text=f"{self.pct:.0f} %  ({self.pct_src})", fg=FG)

        self.draw_gauge()
        self.draw_chart()

    def draw_gauge(self):
        c = self.gauge
        c.delete("all")
        w = c.winfo_width()
        if w < 40:
            return
        x0, x1, y, h = 6, w - 6, 30, 20
        span = FULL_MV - EMPTY_MV

        def px(mv):
            return x0 + (x1 - x0) * (mv - EMPTY_MV) / span

        c.create_rectangle(x0, y, x1, y + h, fill="#1b1f28", outline=GRID)
        # the sub-3.70 V zone, where the ring simply cannot run
        c.create_rectangle(x0, y, px(LED_FLOOR_MV), y + h,
                           fill="#2a1b1b", outline="")
        if self.mv is not None:
            fill = GOOD if self.mv >= LED_FLOOR_MV else WARN
            c.create_rectangle(x0, y, max(px(self.mv), x0 + 1), y + h,
                               fill=fill, outline="")
        fx = px(LED_FLOOR_MV)
        c.create_line(fx, y - 8, fx, y + h + 6, fill=BAD, width=2)
        c.create_text(fx, y - 14, text="3.70 LED floor", fill=BAD,
                      font=self.f_small)
        c.create_text(x0, y + h + 12, text="3.00", fill=DIM, anchor="w",
                      font=self.f_small)
        c.create_text(x1, y + h + 12, text="4.20", fill=DIM, anchor="e",
                      font=self.f_small)

    def draw_chart(self):
        c = self.chart
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 60 or h < 40 or len(self.hist) < 2:
            if len(self.hist) < 2 and w > 60:
                c.create_text(w / 2, h / 2, text="waiting for samples…",
                              fill=DIM, font=self.f_small)
            return
        now = self.hist[-1][0]
        pts = [p for p in self.hist if p[0] >= now - CHART_WINDOW_S]
        if len(pts) < 2:
            return
        L, R, T, B = 52, w - 8, 10, h - 20
        lo = min(p[1] for p in pts)
        hi = max(p[1] for p in pts)
        # always keep the LED floor on screen — it is the point of the chart
        lo, hi = min(lo, LED_FLOOR_MV) - 15, max(hi, LED_FLOOR_MV) + 15
        t_lo, t_hi = pts[0][0], max(pts[-1][0], pts[0][0] + 1)

        def X(t):
            return L + (R - L) * (t - t_lo) / (t_hi - t_lo)

        def Y(mv):
            return B - (B - T) * (mv - lo) / (hi - lo)

        step = 50 if (hi - lo) <= 300 else 100
        g = int(lo // step) * step
        while g <= hi:
            if lo <= g <= hi:
                c.create_line(L, Y(g), R, Y(g), fill=GRID)
                c.create_text(L - 6, Y(g), text=f"{g / 1000:.2f}", fill=DIM,
                              anchor="e", font=self.f_small)
            g += step
        if lo <= LED_FLOOR_MV <= hi:
            c.create_line(L, Y(LED_FLOOR_MV), R, Y(LED_FLOOR_MV), fill=BAD,
                          width=2, dash=(5, 3))
        flat = []
        for t, mv in pts:
            flat += [X(t), Y(mv)]
        c.create_line(*flat, fill=ACCENT, width=2)
        c.create_oval(X(pts[-1][0]) - 3, Y(pts[-1][1]) - 3,
                      X(pts[-1][0]) + 3, Y(pts[-1][1]) + 3,
                      fill=ACCENT, outline="")
        c.create_text(L, B + 12, text=f"-{int((t_hi - t_lo) / 60)} min",
                      fill=DIM, anchor="w", font=self.f_small)
        c.create_text(R, B + 12, text="now", fill=DIM, anchor="e",
                      font=self.f_small)

    def close(self):
        self.reader.stop()
        if self.csv:
            self.csv.close()
        self.root.destroy()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", help="serial port (default: autodetect USB 2e8a)")
    ap.add_argument("--csv", help="also append samples to this CSV")
    args = ap.parse_args()
    root = tk.Tk()
    App(root, args)
    root.mainloop()


if __name__ == "__main__":
    main()
