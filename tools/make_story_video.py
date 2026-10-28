"""Short terminal "stories" that end in the animated Unseenet logo.

Someone types in a terminal, top left, with human pauses and corrections; an
answer comes back; the terminal fades and the logo is drawn
(tools/make_logo_video.py), ending on "usenet, unseen." and a blinking cursor.

    pip install fonttools cairosvg      # plus ffmpeg on PATH
    python tools/make_story_video.py STORY out.mp4|out.gif [--hold 6] [--once] [--size 1280x720]

STORY is one of: anyone, decides. The GIFs in assets/ are made with:

    python tools/make_story_video.py anyone assets/story-anyone.gif
    python tools/make_story_video.py decides assets/story-decides.gif
"""
import os
import random
import subprocess
import sys

import cairosvg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_logo_video as logo  # noqa: E402  (geometry, colours, fonts, logo frames)

FPS = 30
FONT_SIZE = 30
LINE_H = 50
MARGIN_X, MARGIN_Y = 70, 80
FADE = 0.9            # terminal fades out before the logo starts

# A story is a list of steps:
#   ("me", text)       new line from the person typing, typed by hand
#   ("them", text)     new line from the other side, typed steadily
#   ("add", text)      more text on the current line
#   ("back", n)        delete n characters
#   ("pause", s)       wait, cursor blinking
STORIES = {
    "anyone": [
        ("pause", 1.0),
        ("me", "hello? anyone there?"),
        ("pause", 2.4),
        ("me", "i have something to tell."),
        ("pause", 0.9),
        ("me", "but i'm afraid to say it where they can see"),
        ("pause", 1.1),
        ("back", len("where they can see")),
        ("pause", 0.5),
        ("add", "out loud."),
        ("pause", 2.8),
        ("them", "you can say it here."),
        ("pause", 0.6),
        ("them", "no one needs to know who you are"),
        ("pause", 0.35),
        ("add", " or where you are."),
        ("pause", 2.6),
    ],
    "decides": [
        ("pause", 1.0),
        ("me", "who decides what i see?"),
        ("pause", 2.0),
        ("me", "the feed picks it for me."),
        ("pause", 0.8),
        ("me", "what keeps me scrolling, not what i asked for"),
        ("pause", 0.5),
        ("add", "."),
        ("pause", 2.6),
        ("them", "here, you do."),
        ("pause", 0.8),
        ("them", "the groups you choose,"),
        ("add", " in the order they were written."),
        ("pause", 0.7),
        ("them", "no company's algorithm."),
        ("pause", 0.5),
        ("them", "only your own rules decide."),
        ("pause", 2.6),
    ],
}

PREFIX = {"me": "> ", "them": "< "}


def compile_story(steps, seed=7):
    """Turn steps into snapshots: (time, lines, typing) with lines = [(role, text)]."""
    rnd = random.Random(seed)
    t, lines, snaps = 0.0, [], []

    def snap(typing=True):
        snaps.append((t, [tuple(l) for l in lines], typing))

    def type_chars(role, text):
        nonlocal t
        for ch in text:
            if role == "me":
                d = rnd.uniform(0.05, 0.13)
                if ch in " ,": d += rnd.uniform(0.03, 0.12)
                if ch in ".?": d += rnd.uniform(0.10, 0.25)
            else:
                d = 0.045
            t += d
            lines[-1][1] += ch
            snap()

    for step in steps:
        kind = step[0]
        if kind == "pause":
            snap(False); t += step[1]
        elif kind in ("me", "them"):
            if lines:
                t += 0.25 if kind == "me" else 0.15
            lines.append([kind, ""]); snap()
            type_chars(kind, step[1])
        elif kind == "add":
            type_chars(lines[-1][0], step[1])
        elif kind == "back":
            for _ in range(step[1]):
                t += 0.04
                lines[-1][1] = lines[-1][1][:-1]; snap()
    snap(False)
    return snaps, t


class Glyphs:
    def __init__(self, size):
        self.cache = {}
        self.size = size
        _, self.adv = logo.text_paths("M", logo.REG, size, 0, 0)

    def path(self, ch):
        if ch not in self.cache:
            self.cache[ch] = logo.text_paths(ch, logo.REG, self.size, 0, 0)[0][0][0] if ch != " " else ""
        return self.cache[ch]


def terminal_svg(t, snaps, end, W, H, g):
    i = max(k for k, s in enumerate(snaps) if s[0] <= t) if t >= snaps[0][0] else 0
    st, lines, typing = snaps[i]
    since = t - st
    alpha = 1 - logo.clamp((t - end) / FADE)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
           f'<rect width="{W}" height="{H}" fill="{logo.BG}"/>',
           f'<g opacity="{alpha:.3f}">']
    for n, (role, text) in enumerate(lines):
        y = MARGIN_Y + n * LINE_H
        full = PREFIX[role] + text
        for c, ch in enumerate(full):
            d = g.path(ch)
            if not d:
                continue
            if c < 2:
                col = logo.ACCENT
            else:
                col = logo.FG if role == "me" else logo.ACCENT
            out.append(f'<path d="{d}" fill="{col}" transform="translate({MARGIN_X + c * g.adv:.1f},{y})"/>')
    if lines:
        n = len(lines) - 1
        col = len(PREFIX[lines[-1][0]]) + len(lines[-1][1])
        solid = since < 0.35 or (typing and since < 0.3)
        if solid or int((since - 0.35) / 0.5) % 2 == 1:
            x = MARGIN_X + col * g.adv
            y = MARGIN_Y + n * LINE_H
            out.append(f'<rect x="{x + 2:.1f}" y="{y - FONT_SIZE * 0.78:.1f}" width="{g.adv - 3:.1f}" '
                       f'height="{FONT_SIZE * 0.98:.1f}" fill="{logo.ACCENT}" fill-opacity=".85"/>')
    out.append('</g></svg>')
    return "".join(out)


def main():
    args = sys.argv[1:]
    story = args[0]
    out = args[1]
    W, H = 1280, 720
    if "--size" in args:
        W, H = map(int, args[args.index("--size") + 1].split("x"))
    hold = float(args[args.index("--hold") + 1]) if "--hold" in args else 6.0
    snaps, end = compile_story(STORIES[story])
    g = Glyphs(FONT_SIZE)
    logo_start = end + FADE + 0.2
    total = logo_start + logo.DUR + hold

    def frame(t):
        if t < logo_start:
            return terminal_svg(t, snaps, end, W, H, g)
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
                        "fps=20,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=64[p];[b][p]paletteuse",
                        "-loop", "-1" if "--once" in args else "0", gif], check=True)
        os.remove(out)
        print("wrote", gif)
    else:
        print("wrote", out)


if __name__ == "__main__":
    main()
