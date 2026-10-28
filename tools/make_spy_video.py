"""Two short spy-style intros that end in the animated Unseenet logo.

  searchlight  A searchlight (the watcher, in amber) sweeps a night street of
               nodes. An agent slips from shadow to shadow, hides behind a
               dumpster while the light passes, and disappears through a green
               node door. The light finds nothing and switches off.
  trace        A surveillance screen finds a post on a node and traces it back
               hop by hop. Each hop makes the trace less certain until it is
               lost: "SIGNAL LOST".

Both then type "no one sees who you are, or where you are, unless you want
them to." and fade into the logo animation (tools/make_logo_video.py).
Amber is always the watcher; green is always Unseenet.

    pip install fonttools cairosvg      # plus ffmpeg on PATH
    python tools/make_spy_video.py searchlight assets/spy-searchlight.gif
    python tools/make_spy_video.py trace assets/spy-trace.gif
    # options: out.mp4|out.gif, --hold 6, --once, --frame T (writes a PNG)
"""
import math
import os
import random
import subprocess
import sys

import cairosvg
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_logo_video as logo  # noqa: E402

FPS = 30
W, H = 1280, 720
BG, FG, ACCENT, MUTED = logo.BG, logo.FG, logo.ACCENT, logo.MUTED
AMBER = "#ffc35c"
clamp, prog, ease, ease_io = logo.clamp, logo.prog, logo.ease, logo.ease_io

CAPTION = ["no one sees who you are,", "or where you are,", "unless you want them to."]


# --- text ------------------------------------------------------------------
class Mono:
    def __init__(self):
        self.fonts = {}
        self.cache = {}

    def _font(self, path):
        if path not in self.fonts:
            f = TTFont(path)
            self.fonts[path] = (f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm)
        return self.fonts[path]

    def glyph(self, path, ch):
        key = (path, ch)
        if key not in self.cache:
            gs, cmap, upm = self._font(path)
            g = cmap.get(ord(ch), cmap[ord("?")])
            pen = SVGPathPen(gs)
            gs[g].draw(pen)
            self.cache[key] = (pen.getCommands(), gs[g].width)
        return self.cache[key]

    def adv(self, size, path=logo.REG):
        gs, cmap, upm = self._font(path)
        return self.glyph(path, "M")[1] * size / upm

    def text(self, s, x, y, size, fill, opacity=1.0, path=logo.REG):
        gs, cmap, upm = self._font(path)
        sc = size / upm
        out = [f'<g fill="{fill}" fill-opacity="{opacity:.3f}">']
        for i, ch in enumerate(s):
            d, w = self.glyph(path, ch)
            if d:
                out.append(f'<path d="{d}" transform="translate({x + i * w * sc:.1f},{y:.1f}) '
                           f'scale({sc:.5f},{-sc:.5f})"/>')
        out.append("</g>")
        return "".join(out)


MONO = Mono()


def keyframes(kf, t):
    if t <= kf[0][0]:
        return kf[0][1]
    for (t0, v0), (t1, v1) in zip(kf, kf[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * ease_io((t - t0) / (t1 - t0))
    return kf[-1][1]


def caption_svg(t, t0):
    """Typed caption, centred block; returns (svg, end_time)."""
    size, lh, step = 40, 62, 0.055
    adv = MONO.adv(size)
    width = max(len(l) for l in CAPTION) * adv
    x0 = (W - width) / 2
    y0 = H / 2 - lh + 14
    starts, t_cur = [], t0
    for l in CAPTION:
        starts.append(t_cur)
        t_cur += len(l) * step + 0.45
    done = t_cur
    end = done + 2.2
    alpha = 1 - prog(t, end, end + 0.8)
    out = []
    cur = None
    for i, (l, ts) in enumerate(zip(CAPTION, starts)):
        n = 0 if t < ts else min(len(l), int((t - ts) / step) + 1)
        if n:
            col = ACCENT if i == len(CAPTION) - 1 else FG
            out.append(MONO.text(l[:n], x0, y0 + i * lh, size, col, alpha))
        if t >= ts:
            cur = (x0 + n * adv, y0 + i * lh)
    if cur and t < end + 0.8 and t >= t0:
        idle = t - done
        if idle < 0 or int(idle / 0.5) % 2 == 0:
            out.append(f'<rect x="{cur[0] + 3:.1f}" y="{cur[1] - size * 0.78:.1f}" width="{adv - 4:.1f}" '
                       f'height="{size * 0.98:.1f}" fill="{ACCENT}" fill-opacity="{0.85 * alpha:.3f}"/>')
    return "".join(out), end + 0.8


def svg_open():
    return [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
            f'<rect width="{W}" height="{H}" fill="{BG}"/>']


# --- scene 1: searchlight ----------------------------------------------------
GROUND = 600
BUILDINGS = [(30, 140, 230), (210, 120, 300), (350, 170, 200), (560, 150, 330),
             (735, 160, 250), (930, 130, 290), (1085, 110, 220)]
NODE_B = [2, 5]
DOOR_X = 995
DUMP = (615, 554, 80, 46)
SRC = (1235, 72)
rnd = random.Random(3)
WINDOWS = []
for bx, bw, bh in BUILDINGS:
    for wy in range(GROUND - bh + 24, GROUND - 60, 34):
        for wx in range(bx + 16, bx + bw - 22, 30):
            if rnd.random() < 0.45:
                WINDOWS.append((wx, wy, rnd.random() < 0.12))
STARS = [(rnd.uniform(0, W), rnd.uniform(10, 260), rnd.uniform(0.6, 1.6)) for _ in range(45)]

LIGHT_KF = [(0, 1000), (1.0, 900), (4.0, 340), (4.4, 365), (4.8, 335), (7.6, 1100), (8.8, 700),
            (9.8, 620), (11.2, 200), (11.6, 200), (14.0, 990), (14.4, 930), (14.8, 1050), (15.2, 990)]
AGENT_KF = [(0, -60), (1.0, -60), (2.4, 195), (5.2, 195), (6.6, 655), (10.7, 655), (12.0, DOOR_X)]
SCENE1_END = 16.6          # scene faded to black; caption starts
LIGHT_OFF = (15.2, 15.9)


def agent_x(t):
    # linear between keyframes: running at constant speed looks right
    kf = AGENT_KF
    if t <= kf[0][0]:
        return kf[0][1]
    for (t0, v0), (t1, v1) in zip(kf, kf[1:]):
        if t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return kf[-1][1]


def agent_svg(t):
    ax = agent_x(t)
    moving = abs(agent_x(t + 0.02) - ax) > 0.05
    crouch = prog(t, 6.6, 6.9) * (1 - prog(t, 10.4, 10.7))
    opacity = 1 - prog(t, 12.05, 12.45)
    if opacity <= 0 or ax < -40:
        return ""
    phase = ax / 11.0
    swing = math.sin(phase) * (0.55 if moving else 0)
    lean = 7 if moving else 0
    bob = abs(math.sin(phase)) * 3 if moving else math.sin(t * 2.2) * 0.8
    hip = GROUND - 40 - bob
    sh = hip - 36
    col = "#040b09"
    s = [f'<g fill="{col}" stroke="{col}" opacity="{opacity:.3f}" '
         f'transform="translate({ax:.1f},{GROUND}) scale(1,{1 - 0.64 * crouch:.3f}) translate({-ax:.1f},{-GROUND})">']
    for a in (swing, -swing):
        fx, fy = ax + math.sin(a) * 40, hip + math.cos(a) * 40
        s.append(f'<line x1="{ax:.1f}" y1="{hip:.1f}" x2="{fx:.1f}" y2="{min(fy, GROUND):.1f}" '
                 f'stroke-width="7" stroke-linecap="round"/>')
    for a in (-swing * 0.8, swing * 0.8):          # arms
        s.append(f'<line x1="{ax + lean * 0.7:.1f}" y1="{sh + 4:.1f}" x2="{ax + lean * 0.4 + math.sin(a) * 30:.1f}" '
                 f'y2="{sh + 4 + math.cos(a) * 30:.1f}" stroke-width="6" stroke-linecap="round"/>')
    s.append(f'<polygon stroke="none" points="{ax - 11 + lean:.1f},{sh:.1f} {ax + 11 + lean:.1f},{sh:.1f} '
             f'{ax + 15:.1f},{hip + 8:.1f} {ax - 15:.1f},{hip + 8:.1f}"/>')      # coat
    hx, hy = ax + lean + 2, sh - 9
    s.append(f'<circle stroke="none" cx="{hx:.1f}" cy="{hy:.1f}" r="8.5"/>')
    s.append(f'<rect stroke="none" x="{hx - 14:.1f}" y="{hy - 8:.1f}" width="28" height="3.5" rx="1.5"/>')
    s.append(f'<rect stroke="none" x="{hx - 8:.1f}" y="{hy - 18:.1f}" width="16" height="11" rx="2"/>')
    s.append("</g>")
    return "".join(s)


def searchlight_frame(t):
    out = svg_open()
    fade_in = prog(t, 0, 1.0)
    fade_out = 1 - prog(t, 15.9, SCENE1_END)
    vis = fade_in * fade_out
    out.append(f'<g opacity="{vis:.3f}">')
    for x, y, r in STARS:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{MUTED}" fill-opacity=".3"/>')
    # network links between the node roofs and off screen
    roofs = [(BUILDINGS[i][0] + BUILDINGS[i][1] / 2, GROUND - BUILDINGS[i][2] - 18) for i in NODE_B]
    links = [(roofs[0], roofs[1]), (roofs[0], (-20, 170)), (roofs[1], (1300, 160)), (roofs[1], (760, -20))]
    pulse = prog(t, 12.9, 14.3)
    for (a, b) in links:
        out.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{ACCENT}" '
                   f'stroke-opacity="{0.16 + 0.3 * math.sin(math.pi * pulse):.3f}" stroke-width="2" stroke-dasharray="3 7"/>')
    # buildings
    for bx, bw, bh in BUILDINGS:
        out.append(f'<rect x="{bx}" y="{GROUND - bh}" width="{bw}" height="{bh}" fill="#16362e"/>')
    for wx, wy, warm in WINDOWS:
        out.append(f'<rect x="{wx}" y="{wy}" width="12" height="16" fill="{"#3d4a32" if warm else "#1f4a3f"}"/>')
    # roof nodes
    for i, (rx, ry) in zip(NODE_B, roofs):
        out.append(f'<line x1="{rx:.1f}" y1="{ry:.1f}" x2="{rx:.1f}" y2="{ry + 18:.1f}" stroke="{MUTED}" stroke-width="2"/>')
        glow = math.sin(math.pi * prog(t, 12.9 + (0.5 if i == 2 else 0), 13.9 + (0.5 if i == 2 else 0)))
        if glow > 0:
            out.append(f'<circle cx="{rx:.1f}" cy="{ry:.1f}" r="{7 + 14 * glow:.1f}" fill="{ACCENT}" fill-opacity="{0.25 * glow:.3f}"/>')
        out.append(f'<circle cx="{rx:.1f}" cy="{ry:.1f}" r="8" fill="{ACCENT}" fill-opacity="{0.55 + 0.45 * glow:.3f}"/>')
    # travelling pulse along the links
    if 0 < pulse < 1:
        for (a, b) in links:
            p = ease(pulse)
            px, py = a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p
            out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4" fill="{ACCENT}" fill-opacity="{1 - pulse:.3f}"/>')
    # ground and door
    out.append(f'<rect x="0" y="{GROUND}" width="{W}" height="{H - GROUND}" fill="#0b211b"/>')
    out.append(f'<line x1="0" y1="{GROUND + 1}" x2="{W}" y2="{GROUND + 1}" stroke="#1f4a3f" stroke-width="2"/>')
    door = ease(prog(t, 11.7, 12.0)) * (1 - ease(prog(t, 12.5, 12.8)))
    out.append(f'<rect x="{DOOR_X - 16}" y="{GROUND - 46}" width="32" height="46" fill="#0b211b"/>')
    if door > 0:
        out.append(f'<rect x="{DOOR_X - 16}" y="{GROUND - 46}" width="{32 * door:.1f}" height="46" '
                   f'fill="{ACCENT}" fill-opacity=".75"/>')
        out.append(f'<polygon points="{DOOR_X - 16},{GROUND} {DOOR_X - 16 + 32 * door:.1f},{GROUND} '
                   f'{DOOR_X + 16 + 40 * door:.1f},{GROUND + 40} {DOOR_X - 30},{GROUND + 40}" '
                   f'fill="{ACCENT}" fill-opacity="{0.18 * door:.3f}"/>')
    out.append(agent_svg(t))
    dx, dy, dw, dh = DUMP
    out.append(f'<rect x="{dx}" y="{dy}" width="{dw}" height="{dh}" rx="3" fill="#0d2a22" stroke="#21493e" stroke-width="2"/>')
    out.append(f'<line x1="{dx - 3}" y1="{dy + 2}" x2="{dx + dw + 3}" y2="{dy + 2}" stroke="#2a5a4c" stroke-width="4"/>')
    # tower
    tx, ty = SRC
    for x1 in (tx - 22, tx + 22):
        out.append(f'<line x1="{x1}" y1="{GROUND}" x2="{tx}" y2="{ty + 16}" stroke="#21493e" stroke-width="4"/>')
    for k in range(5):
        y = GROUND - 40 - k * 95
        hw = 22 * (y - ty - 16) / (GROUND - ty - 16)
        out.append(f'<line x1="{tx - hw:.1f}" y1="{y}" x2="{tx + hw:.1f}" y2="{y - 60}" stroke="#1a3d34" stroke-width="2"/>')
    # the light: amber, flickers and dies at the end
    on = 1 - prog(t, *LIGHT_OFF)
    if LIGHT_OFF[0] < t < LIGHT_OFF[1]:
        on *= 0.4 + 0.6 * (int(t * 22) % 3 != 0)
    sx = keyframes(LIGHT_KF, t)
    if on > 0:
        out.append(f'<defs><linearGradient id="cone" gradientUnits="userSpaceOnUse" x1="{tx}" y1="{ty}" '
                   f'x2="{sx:.1f}" y2="{GROUND}"><stop offset="0" stop-color="{AMBER}" stop-opacity=".42"/>'
                   f'<stop offset="1" stop-color="{AMBER}" stop-opacity=".16"/></linearGradient></defs>')
        out.append(f'<polygon points="{tx - 5},{ty} {tx + 5},{ty} {sx + 82:.1f},{GROUND} {sx - 82:.1f},{GROUND}" '
                   f'fill="url(#cone)" opacity="{on:.3f}"/>')
        out.append(f'<ellipse cx="{sx:.1f}" cy="{GROUND + 4}" rx="92" ry="16" fill="{AMBER}" fill-opacity="{0.30 * on:.3f}"/>')
    ang = math.degrees(math.atan2(GROUND - ty, sx - tx))
    out.append(f'<g transform="translate({tx},{ty}) rotate({ang:.1f})"><rect x="-14" y="-10" width="26" height="20" '
               f'rx="4" fill="#1a3d34"/><rect x="10" y="-9" width="5" height="18" fill="{AMBER}" '
               f'fill-opacity="{0.15 + 0.85 * on:.3f}"/></g>')
    out.append("</g>")
    cap, cap_end = caption_svg(t, SCENE1_END + 0.3)
    out.append(cap)
    out.append("</svg>")
    return "".join(out), cap_end


# --- scene 2: trace ------------------------------------------------------------
NODE = (1040, 430)
HOPS = [(840, 250), (590, 470), (360, 280)]          # traced backwards from NODE
HOP_T = [(3.2, 4.4), (5.0, 6.2), (6.8, 8.0)]
CONF = [97, 61, 26, 4]
UNC = [16, 70, 170, 340]
rnd2 = random.Random(11)
DOTS = [(rnd2.uniform(60, W - 60), rnd2.uniform(140, H - 80)) for _ in range(150)]
SCENE2_END = 13.0


def along(values, t):
    """A value that moves from values[k] to values[k+1] while hop k is traced."""
    v = values[0]
    for k, (a, b) in enumerate(HOP_T):
        v += (values[k + 1] - values[k]) * ease(prog(t, a, b))
    return v


def wobble(t, k, amp):
    return (amp * math.sin(t * 3.1 + k), amp * math.cos(t * 2.3 + 2 * k))


def trace_frame(t):
    out = svg_open()
    vis = prog(t, 0, 1.0) * (1 - prog(t, 12.0, 12.8))
    out.append(f'<g opacity="{vis:.3f}">')
    for x in range(0, W + 1, 80):
        out.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}" stroke="#1a4036" stroke-opacity=".5"/>')
    for y in range(0, H + 1, 80):
        out.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="#1a4036" stroke-opacity=".5"/>')
    for x, y in DOTS:
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2" fill="{MUTED}" fill-opacity=".22"/>')
    for x, y in HOPS:
        out.append(f'<circle cx="{x}" cy="{y}" r="7" fill="none" stroke="{MUTED}" stroke-opacity=".5" stroke-width="2"/>')
    # the node with the post (green: Unseenet)
    nx, ny = NODE
    out.append(f'<circle cx="{nx}" cy="{ny}" r="9" fill="none" stroke="{ACCENT}" stroke-width="2.5"/>')
    pp = logo.back(prog(t, 1.0, 1.4)) if t > 1.0 else 0
    if pp > 0:
        out.append(f'<circle cx="{nx}" cy="{ny}" r="{5 * pp:.1f}" fill="{ACCENT}"/>')
        out.append(MONO.text("post <3f9a1c>", nx + 18, ny + 30, 16, MUTED, clamp(pp)))
    # trace lines, less sure at every hop
    chain = [NODE] + HOPS
    for k, (a, b) in enumerate(zip(chain, chain[1:])):
        p = ease(prog(t, *HOP_T[k]))
        if p > 0:
            ex, ey = a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p
            dash = ["", ' stroke-dasharray="10 6"', ' stroke-dasharray="4 10"'][k]
            out.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{ex:.1f}" y2="{ey:.1f}" stroke="{AMBER}" '
                       f'stroke-opacity="{[0.9, 0.6, 0.35][k]}" stroke-width="2.5"{dash}/>')
            if p >= 1:
                out.append(MONO.text("?" * k, b[0] + 14, b[1] - 12, 18, AMBER, 0.7))
    # failed attempts beyond the last hop
    lx, ly = HOPS[-1]
    for k in range(5):
        a0 = 8.4 + k * 0.32
        if a0 < t < a0 + 0.26:
            ang = k * 2.4 + 0.7
            L = 60 + 25 * k
            out.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + L * math.cos(ang):.1f}" y2="{ly + L * math.sin(ang):.1f}" '
                       f'stroke="{AMBER}" stroke-opacity=".35" stroke-width="2" stroke-dasharray="3 6"/>')
    # crosshair: flies in, locks, follows, then wanders
    stage = sum(1 for a, b in HOP_T if t >= b)
    if t < 2.0:
        p = ease(prog(t, 1.2, 2.0))
        cx, cy = W / 2 + (nx - W / 2) * p, H / 2 + (ny - H / 2) * p
    elif t < 8.4:
        k = sum(1 for a, b in HOP_T if t >= a) - 1
        if k < 0:
            cx, cy = nx, ny
        else:
            a, b = chain[k], chain[k + 1]
            p = ease(prog(t, *HOP_T[k]))
            cx, cy = a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p
        wx, wy = wobble(t, 1, [0, 3, 8, 16][stage])
        cx, cy = cx + wx, cy + wy
    else:
        p = prog(t, 8.4, 9.6)
        wx, wy = wobble(t * 1.7, 4, 40 + 160 * p)
        cx, cy = lx + (W / 2 - lx) * p + wx, ly + (H / 2 - ly) * p + wy
    unc = along(UNC, t) + 700 * ease(prog(t, 8.4, 9.8))
    if t > 1.2:
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{unc:.1f}" fill="{AMBER}" fill-opacity=".05" '
                   f'stroke="{AMBER}" stroke-opacity=".5" stroke-width="1.5" stroke-dasharray="6 8"/>')
        out.append(f'<g stroke="{AMBER}" stroke-width="2.5" fill="none"><circle cx="{cx:.1f}" cy="{cy:.1f}" r="18"/>')
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            out.append(f'<line x1="{cx + dx * 10:.1f}" y1="{cy + dy * 10:.1f}" x2="{cx + dx * 28:.1f}" y2="{cy + dy * 28:.1f}"/>')
        out.append("</g>")
    # HUD
    for (x, y, sx, sy) in ((24, 24, 1, 1), (W - 24, 24, -1, 1), (24, H - 24, 1, -1), (W - 24, H - 24, -1, -1)):
        out.append(f'<path d="M{x},{y + 30 * sy} L{x},{y} L{x + 30 * sx},{y}" stroke="{AMBER}" stroke-width="3" fill="none"/>')
    out.append(MONO.text("TRACE 0451 // ORIGIN SEARCH", 48, 64, 22, AMBER))
    if int(t / 0.6) % 2 == 0:
        out.append(f'<circle cx="{W - 130}" cy="57" r="7" fill="{AMBER}"/>')
    out.append(MONO.text("REC", W - 115, 64, 20, AMBER))
    if t < 2.4:
        status = "SCANNING..." if t < 1.0 else "POST FOUND - LOCKING"
    elif t < 8.4:
        status = f"TRACING ORIGIN - HOP {min(3, stage + 1)}"
    elif t < 9.4:
        status = "TRACING ORIGIN - HOP ?"
    else:
        status = "ORIGIN: UNKNOWN"
    out.append(MONO.text("STATUS  " + status, 48, 100, 18, FG, 0.9))
    if t < 8.4:
        conf = round(along(CONF, t))
        ctext = f"{conf:3d}%"
    else:
        conf, ctext = 0, " --"
    if t > 2.4:
        out.append(MONO.text("CONFIDENCE " + ctext, 48, 130, 18, FG, 0.9))
        out.append(f'<rect x="300" y="117" width="200" height="12" fill="none" stroke="{AMBER}" stroke-opacity=".6"/>')
        out.append(f'<rect x="300" y="117" width="{2 * conf:.1f}" height="12" fill="{AMBER}" fill-opacity=".7"/>')
    out.append(MONO.text(f"T+00:{int(t):02d}.{int(t * 100) % 100:02d}", 48, H - 44, 18, MUTED))
    out.append(MONO.text(f"X {int(cx) if t > 1.2 else 0:4d}  Y {int(cy) if t > 1.2 else 0:4d}", W - 260, H - 44, 18, MUTED))
    if t > 9.4 and int((t - 9.4) / 0.45) % 2 == 0:
        size = 64
        s = "SIGNAL LOST"
        out.append(f'<rect x="{W / 2 - 260}" y="{H / 2 - 62}" width="520" height="96" fill="{BG}" fill-opacity=".8"/>')
        out.append(MONO.text(s, W / 2 - len(s) * MONO.adv(size, logo.BOLD) / 2, H / 2 + 8, size, AMBER, 1, logo.BOLD))
    out.append("</g>")
    cap, cap_end = caption_svg(t, SCENE2_END)
    out.append(cap)
    out.append("</svg>")
    return "".join(out), cap_end


SCENES = {"searchlight": searchlight_frame, "trace": trace_frame}


def main():
    args = sys.argv[1:]
    scene, out = SCENES[args[0]], args[1]
    hold = float(args[args.index("--hold") + 1]) if "--hold" in args else 6.0
    _, cap_end = scene(0)
    logo_start = cap_end + 0.4
    total = logo_start + logo.DUR + hold

    def frame(t):
        if t < logo_start:
            return scene(t)[0]
        return logo.frame_svg(t - logo_start, W, H)

    if "--frame" in args:
        t = float(args[args.index("--frame") + 1])
        cairosvg.svg2png(bytestring=frame(t).encode(), write_to=out)
        return
    gif = None
    if out.endswith(".gif"):
        gif, out = out, out[:-4] + ".tmp.mp4"
    tmp = out[:-4] + ".part.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
         "-c:v", "png", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp], stdin=subprocess.PIPE)
    for f in range(int(total * FPS)):
        ff.stdin.write(cairosvg.svg2png(bytestring=frame(f / FPS).encode()))
    ff.stdin.close()
    if ff.wait() != 0:
        sys.exit("ffmpeg failed")
    os.replace(tmp, out)
    if gif:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-vf",
                        "fps=20,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64:stats_mode=diff[p];"
                        "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        "-loop", "-1" if "--once" in args else "0", gif], check=True)
        os.remove(out)
        print("wrote", gif)
    else:
        print("wrote", out, f"({total:.1f} s)")


if __name__ == "__main__":
    main()
