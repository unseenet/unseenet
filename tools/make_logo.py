"""Generate the Unseenet logo files in assets/.

The icon is a closed eye ("unseen") whose lashes end in linked nodes ("net").
The wordmark is DejaVu Sans Mono Bold converted to outlines, so the SVGs render
the same everywhere without fonts.

    pip install fonttools cairosvg
    python tools/make_logo.py
"""
import math
import os

import cairosvg

os.chdir(os.path.join(os.path.dirname(__file__), "..", "assets"))
import math
# Closed eye = "unseen"; the lashes end in nodes linked into a small net = "net".
W=128
arc=lambda t:( (14+100*t), 44+ 4*18*t*(1-t) )   # eyelid: quadratic-like curve, lowest in middle
def lid_path():
    pts=[arc(i/40) for i in range(41)]
    return "M"+" L".join(f"{x:.1f},{y:.1f}" for x,y in pts)
lash_t=[0.12,0.31,0.5,0.69,0.88]
nodes=[]
for t in lash_t:
    x,y=arc(t)
    # direction: outward normal (downward), fanned
    ang=math.radians(90-(t-0.5)*100)
    L=30 if t==0.5 else 27
    nodes.append((x,y,x+L*math.cos(ang),y+L*math.sin(ang)))
def svg(fg, accent, bg=None, size=W):
    s=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {W}" width="{size}" height="{size}">']
    if bg:
        s.append(f'<rect width="{W}" height="{W}" rx="28" fill="{bg}"/>')
        s.append('<g transform="translate(64,61) scale(0.76) translate(-64,-52)">')
    # faint dashed upper lid: the eye that is not there
    s.append(f'<path d="M14,44 Q64,4 114,44" fill="none" stroke="{fg}" stroke-opacity=".28" stroke-width="4" stroke-linecap="round" stroke-dasharray="2 9"/>')
    # net links between lash tips
    tips=[(n[2],n[3]) for n in nodes]
    for (a,b) in [(0,1),(1,2),(2,3),(3,4)]:
        s.append(f'<line x1="{tips[a][0]:.1f}" y1="{tips[a][1]:.1f}" x2="{tips[b][0]:.1f}" y2="{tips[b][1]:.1f}" stroke="{accent}" stroke-opacity=".55" stroke-width="2.5"/>')
    for x,y,tx,ty in nodes:
        s.append(f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{tx:.1f}" y2="{ty:.1f}" stroke="{fg}" stroke-width="5" stroke-linecap="round"/>')
    s.append(f'<path d="{lid_path()}" fill="none" stroke="{fg}" stroke-width="7" stroke-linecap="round"/>')
    for i,(x,y,tx,ty) in enumerate(nodes):
        r=6.5 if i==2 else 5
        s.append(f'<circle cx="{tx:.1f}" cy="{ty:.1f}" r="{r}" fill="{accent}"/>')
    if bg: s.append('</g>')
    s.append('</svg>')
    return "\n".join(s)
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

def text_paths(text, font_path, size, x0, baseline, letter=0.0):
    f=TTFont(font_path); gs=f.getGlyphSet(); cmap=f.getBestCmap(); upm=f["head"].unitsPerEm
    sc=size/upm; x=x0; out=[]
    for ch in text:
        g=cmap[ord(ch)]
        pen=SVGPathPen(gs)
        gs[g].draw(TransformPen(pen,(sc,0,0,-sc,x,baseline)))
        out.append(pen.getCommands())
        x+=gs[g].width*sc+letter
    return out, x

BOLD="/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
REG="/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

def icon_inner(fg, accent):
    s=svg(fg,accent)
    return s[s.index(">")+1:s.rindex("</svg>")]

def logo(fg, accent, muted):
    word, wend = text_paths("unseenet", BOLD, 58, 150, 82, letter=-1)
    tag, tend = text_paths("usenet, unseen.", REG, 19, 153, 112, letter=0.5)
    width=int(max(wend,tend))+16
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 140" width="{width*2}" height="280">',
           f'<title>Unseenet</title>',
           f'<g transform="translate(6,10) scale(0.98)">{icon_inner(fg,accent)}</g>']
    for i,d in enumerate(word):
        parts.append(f'<path d="{d}" fill="{accent if i>=5 else fg}"/>')
    for d in tag:
        parts.append(f'<path d="{d}" fill="{muted}"/>')
    parts.append("</svg>")
    return "\n".join(parts)

LIGHT=dict(fg="#10302a", accent="#16a974", muted="#5b6b67")   # for light backgrounds
DARK =dict(fg="#e8f3ef", accent="#34d399", muted="#9fb3ad")    # for dark backgrounds
open("logo-light.svg","w").write(logo(**LIGHT))
open("logo-dark.svg","w").write(logo(**DARK))
open("icon.svg","w").write(svg(LIGHT["fg"],LIGHT["accent"]))
open("icon-dark.svg","w").write(svg(DARK["fg"],DARK["accent"]))
# app/avatar icon on a solid tile, e.g. for GitHub social preview and favicons
open("icon-tile.svg","w").write(svg(DARK["fg"],DARK["accent"],bg="#0f2a24"))
cairosvg.svg2png(url="icon-tile.svg", write_to="icon-512.png", output_width=512)
print("logo files written to assets/")
