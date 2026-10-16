"""The Unseenet logo for text screens: the closed eye, drawn with half blocks.

Each cell of the screen is two "pixels" (▀ with a foreground and a background
colour), so the icon keeps its shape on the Linux console, whose font only has
the CP437 characters. The pixels below were traced from assets/icon-512.png
and made symmetric by hand.

    python -m unseenet.logo     prints it with ANSI colours (the boot splash)
"""

from __future__ import annotations

# w lid and lashes, g the nodes, k the links between them, d the dashed upper lid
ICON = [
    "             dd dd dd             ",
    "          dd  d    d  dd          ",
    "       dd                dd       ",
    "     d                      d     ",
    "    dd                      dd    ",
    "  ww                          ww  ",
    "  www                        www  ",
    "  wwwww                    wwwww  ",
    "    wwwww                wwwww    ",
    "    wwwwwwww          wwwwwwww    ",
    "   www  wwwwwwwwwwwwwwwwww  www   ",
    "   ww     wwwwwwwwwwwwww     ww   ",
    "  ww      ww   wwww   ww      ww  ",
    "ggw       ww    ww    ww       wgg",
    "ggg      ww     ww     ww      ggg",
    "gggkk    ww     ww     ww    kkggg",
    "    kkkkgw      ww      wgkkkk    ",
    "       gggg     ww     gggg       ",
    "       ggggkkk gggg kkkgggg       ",
    "             kkggggkk             ",
    "               gggg               ",
    "                gg                ",
]

WORDMARK = """█ █ █▄ █ ▄▀▀ █▀▀ █▀▀ █▄ █ █▀▀ ▀█▀
█ █ █ ▀█  ▀▄ █▀  █▀  █ ▀█ █▀   █
▀▀▀ ▀  ▀ ▀▀  ▀▀▀ ▀▀▀ ▀  ▀ ▀▀▀  ▀"""

# The logo's colours, and the nearest of the console's 16 (SGR codes).
COLORS = {"w": "#e8f3ef", "g": "#34d399", "k": "#23876a", "d": "#4c625d"}
ANSI_FG = {"w": "97", "g": "92", "k": "32", "d": "90"}
ANSI_BG = {"w": "107", "g": "102", "k": "42", "d": "100"}


def cells(icon: list[str] = ICON):
    """Rows of (character, top pixel, bottom pixel); a pixel is " " when empty."""
    rows = list(icon) + ([" " * len(icon[0])] if len(icon) % 2 else [])
    for top, bottom in zip(rows[0::2], rows[1::2]):
        line = []
        for t, b in zip(top, bottom):
            if t == " " and b == " ":
                line.append((" ", " ", " "))
            elif t == b:
                line.append(("█", t, " "))
            elif t == " ":
                line.append(("▄", b, " "))
            else:
                line.append(("▀", t, b))        # b may be " ": no background
        yield line


def rich_icon():
    """The icon as a rich Text, for a Textual Static."""
    from rich.text import Text
    text = Text(no_wrap=True)
    for n, line in enumerate(cells()):
        if n:
            text.append("\n")
        for ch, fg, bg in line:
            style = ""
            if fg != " ":
                style = COLORS[fg] + (f" on {COLORS[bg]}" if bg != " " else "")
            text.append(ch, style=style)
    return text


def ansi_icon(indent: int = 0) -> str:
    out = []
    for line in cells():
        s = " " * indent
        for ch, fg, bg in line:
            if fg == " ":
                s += ch
            else:
                codes = ANSI_FG[fg] + (";" + ANSI_BG[bg] if bg != " " else "")
                s += f"\033[{codes}m{ch}\033[0m"
        out.append(s.rstrip())
    return "\n".join(out)


def main() -> None:
    import shutil
    width = shutil.get_terminal_size((80, 25)).columns
    pad = max(0, (width - len(ICON[0])) // 2)
    print(ansi_icon(pad))
    print()
    wpad = max(0, (width - len(WORDMARK.splitlines()[0])) // 2)
    for line in WORDMARK.splitlines():
        print(" " * wpad + f"\033[92m{line}\033[0m")


if __name__ == "__main__":
    main()
