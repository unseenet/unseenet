"""Animate the Unseenet logo: the eye is drawn slowly, the nodes light up and
link into a net, then the wordmark appears and "usenet, unseen." is typed
underneath in the logo's own fonts (DejaVu Sans Mono Bold / Regular).

Same geometry and colours as tools/make_logo.py (dark variant).

    pip install fonttools cairosvg      # plus ffmpeg on PATH
    python tools/make_logo_video.py [out.mp4|out.gif] [--size 1280x720] [--hold 6] [--gif] [--once]

The output may be an .mp4, or a .gif (rendered via a temporary .mp4); --gif
with an .mp4 keeps both. --hold adds seconds at the end where only the cursor
blinks; --once makes the GIF play a single time instead of looping.

The GIFs in assets/ are made with:

    python tools/make_logo_video.py assets/logo-animated.gif
    python tools/make_logo_video.py assets/logo-animated-once.gif --hold 2 --once
"""
import math
import os
import subprocess
import sys

import cairosvg
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

FPS = 30
DUR = 9.5        # animation; --hold N adds N seconds of blinking cursor at the end
BG = "#0f2a24"
FG, ACCENT, MUTED = "#e8f3ef", "#34d399", "#9fb3ad"   # DARK in make_logo.py
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

# --- geometry, as in make_logo.py ----------------------------------------
arc = lambda t: (14 + 100 * t, 44 + 4 * 18 * t * (1 - t))
LASH_T = [0.12, 0.31, 0.5, 0.69, 0.88]
NODES = []
for t in LASH_T:
    x, y = arc(t)
    ang = math.radians(90 - (t - 0.5) * 100)
    L = 30 if t == 0.5 else 27
    NODES.append((x, y, x + L * math.cos(ang), y + L * math.sin(ang)))


def text_paths(text, font_path, size, x0, baseline, letter=0.0):
    f = TTFont(font_path); gs = f.getGlyphSet(); cmap = f.getBestCmap()
    sc = size / f["head"].unitsPerEm; x = x0; out = []
    for ch in text:
        g = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, (sc, 0, 0, -sc, x, baseline)))
        out.append((pen.getCommands(), x))
        x += gs[g].width * sc + letter
    return out, x


WORD, WEND = text_paths("unseenet", BOLD, 58, 150, 82, letter=-1)
TAG, TEND = text_paths("usenet, unseen.", REG, 19, 153, 112, letter=0.5)
LOGO_W = int(max(WEND, TEND)) + 16
LOGO_H = 140
CHAR_W_TAG = TAG[1][1] - TAG[0][1]


# --- easing / timing helpers ---------------------------------------------
def clamp(v): return max(0.0, min(1.0, v))
def prog(t, a, b): return clamp((t - a) / (b - a))
def ease(p): return 1 - (1 - p) ** 3                      # ease-out cubic
def ease_io(p): return p * p * (3 - 2 * p)
def back(p, s=2.2):                                       # overshoot pop
    p -= 1
    return 1 + p * p * ((s + 1) * p + s)


def poly(points):
    return "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in points)


def partial_curve(f, p, n=80):
    """Points of curve f(u), u in [0, p]."""
    if p <= 0:
        return None
    k = max(1, int(n * p))
    return [f(p * i / k) for i in range(k + 1)]


quad_upper = lambda u: ((1 - u) ** 2 * 14 + 2 * (1 - u) * u * 64 + u * u * 114,
                        (1 - u) ** 2 * 44 + 2 * (1 - u) * u * 4 + u * u * 44)

# timeline (seconds)
T_UPPER = (0.4, 1.6)
T_LID = (1.0, 2.8)
LASH_DUR = 0.45
T_LINKS = (3.6, 4.6)
T_WORD = 4.5          # first letter; letters 0.11 s apart, each 0.45 s
T_TYPE = 6.0          # tagline typing starts
TYPE_STEP = 0.085


def lash_start(i):
    a, b = T_LID
    return a + ease_io(0) * 0 + (b - a) * LASH_T[i]       # when the lid reaches it


def frame_svg(t, W, H):
    s = LOGO_W * 0.0
    scale = min(W * 0.84 / LOGO_W, H * 0.62 / LOGO_H)
    ox_full = (W - LOGO_W * scale) / 2
    ox_icon = W / 2 - 70 * scale              # icon (logo x 6..134) centred alone
    slide = ease_io(prog(t, T_WORD - 0.7, T_WORD + 0.5))
    ox = ox_icon + (ox_full - ox_icon) * slide
    oy = (H - LOGO_H * scale) / 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           f'<rect width="{W}" height="{H}" fill="{BG}"/>',
           f'<g transform="translate({ox:.2f},{oy:.2f}) scale({scale:.4f})">',
           '<g transform="translate(6,10) scale(0.98)">']

    # dashed upper lid, drawn left to right
    pts = partial_curve(quad_upper, ease_io(prog(t, *T_UPPER)))
    if pts:
        out.append(f'<path d="{poly(pts)}" fill="none" stroke="{FG}" stroke-opacity=".28" '
                   f'stroke-width="4" stroke-linecap="round" stroke-dasharray="2 9"/>')

    # net links between the tips
    tips = [(n[2], n[3]) for n in NODES]
    for k in range(4):
        p = ease(prog(t, T_LINKS[0] + k * 0.18, T_LINKS[0] + k * 0.18 + 0.45))
        if p > 0:
            (x1, y1), (x2, y2) = tips[k], tips[k + 1]
            out.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x1 + (x2 - x1) * p:.2f}" '
                       f'y2="{y1 + (y2 - y1) * p:.2f}" stroke="{ACCENT}" stroke-opacity=".55" '
                       f'stroke-width="2.5" stroke-linecap="round"/>')

    # lashes grow out from the lid as the lid passes them
    for i, (x, y, tx, ty) in enumerate(NODES):
        p = ease(prog(t, lash_start(i), lash_start(i) + LASH_DUR))
        if p > 0:
            out.append(f'<line x1="{x:.2f}" y1="{y:.2f}" x2="{x + (tx - x) * p:.2f}" '
                       f'y2="{y + (ty - y) * p:.2f}" stroke="{FG}" stroke-width="5" stroke-linecap="round"/>')

    # the closed lid itself
    pts = partial_curve(arc, ease_io(prog(t, *T_LID)))
    if pts:
        out.append(f'<path d="{poly(pts)}" fill="none" stroke="{FG}" stroke-width="7" stroke-linecap="round"/>')

    # nodes pop in at the end of each lash, with a soft glow
    for i, (x, y, tx, ty) in enumerate(NODES):
        a = lash_start(i) + LASH_DUR - 0.05
        p = prog(t, a, a + 0.4)
        if p > 0:
            r = (6.5 if i == 2 else 5) * back(p)
            g = prog(t, a, a + 0.25) * (1 - prog(t, a + 0.25, a + 1.0))
            if g > 0:
                out.append(f'<circle cx="{tx:.2f}" cy="{ty:.2f}" r="{r * 2.2:.2f}" fill="{ACCENT}" '
                           f'fill-opacity="{0.22 * g:.3f}"/>')
            out.append(f'<circle cx="{tx:.2f}" cy="{ty:.2f}" r="{r:.2f}" fill="{ACCENT}"/>')
    out.append('</g>')

    # wordmark: letters rise and fade in one by one
    for i, (d, _) in enumerate(WORD):
        p = ease(prog(t, T_WORD + i * 0.11, T_WORD + i * 0.11 + 0.45))
        if p > 0:
            out.append(f'<path d="{d}" fill="{ACCENT if i >= 5 else FG}" fill-opacity="{p:.3f}" '
                       f'transform="translate(0,{(1 - p) * 10:.2f})"/>')

    # tagline: typed, with a terminal block cursor
    n = 0 if t < T_TYPE else min(len(TAG), int((t - T_TYPE) / TYPE_STEP) + 1)
    for d, _ in TAG[:n]:
        out.append(f'<path d="{d}" fill="{MUTED}"/>')
    t_done = T_TYPE + len(TAG) * TYPE_STEP
    cursor_from = T_TYPE - 0.6
    cursor_to = 1e9                      # keeps blinking until the video ends
    if cursor_from <= t < cursor_to:
        typing = t < t_done
        if typing or int((t - cursor_from) / 0.5) % 2 == 0:
            cx = TAG[n][1] if n < len(TAG) else TEND
            out.append(f'<rect x="{cx + 1:.2f}" y="{112 - 15:.2f}" width="{CHAR_W_TAG - 1.5:.2f}" '
                       f'height="18.5" fill="{ACCENT}" fill-opacity=".85"/>')

    out.append('</g></svg>')
    return "".join(out)


def main():
    args = sys.argv[1:]
    out = next((a for a in args if a.endswith((".mp4", ".gif"))), "unseenet-logo.mp4")
    gif = None
    if out.endswith(".gif"):
        gif, out = out, out[:-4] + ".tmp.mp4"
    elif "--gif" in args:
        gif = out[:-4] + ".gif"
    W, H = 1280, 720
    if "--size" in args:
        W, H = map(int, args[args.index("--size") + 1].split("x"))
    if "--frame" in args:                    # preview one frame as PNG
        t = float(args[args.index("--frame") + 1])
        cairosvg.svg2png(bytestring=frame_svg(t, W, H).encode(), write_to=f"frame-{t:.2f}.png")
        return
    tmp = out[:-4] + ".part.mp4"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
         "-c:v", "png", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", tmp], stdin=subprocess.PIPE)
    hold = float(args[args.index("--hold") + 1]) if "--hold" in args else 6.0
    total = int((DUR + hold) * FPS)
    for f in range(total):
        t = f / FPS
        png = cairosvg.svg2png(bytestring=frame_svg(t, W, H).encode())
        ff.stdin.write(png)
    ff.stdin.close()
    if ff.wait() != 0:
        sys.exit("ffmpeg failed")
    os.replace(tmp, out)
    if not out.endswith(".tmp.mp4"):
        print("wrote", out)
    if gif:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-vf",
                        "fps=20,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse",
                        "-loop", "-1" if "--once" in args else "0", gif], check=True)
        print("wrote", gif)
        if out.endswith(".tmp.mp4"):
            os.remove(out)


if __name__ == "__main__":
    main()
