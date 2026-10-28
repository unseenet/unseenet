# Logo

| File | Use |
|------|-----|
| `logo-light.svg` | Logo with wordmark, for light backgrounds |
| `logo-dark.svg`  | Logo with wordmark, for dark backgrounds |
| `icon.svg` / `icon-dark.svg` | Icon only, transparent |
| `icon-tile.svg` / `icon-512.png` | Icon on a dark tile: avatar, favicon, social preview |
| `logo-animated.gif` | The logo drawn, then the tagline typed; loops after 6 s of blinking cursor |
| `logo-animated-once.gif` | The same, played once, ending on the finished logo |
| `story-anyone.gif` | Terminal story: "hello? anyone there?", ending in the logo |
| `story-decides.gif` | Terminal story: "who decides what i see?", ending in the logo |
| `spy-searchlight.gif` | An agent slips past a searchlight into a node, ending in the logo |
| `spy-trace.gif` | A surveillance trace loses a post hop by hop, ending in the logo |

The icon is a closed eye — *unseen* — whose lashes end in linked nodes —
*net*. The dashed upper lid is the eye that isn't there.

Colors: ink `#10302a`, green `#16a974` (light) / `#34d399` (dark).

The wordmark is DejaVu Sans Mono Bold (Bitstream Vera license) converted
to outlines. Regenerate everything with `python tools/make_logo.py`.
The animations are made with `tools/make_logo_video.py`,
`tools/make_story_video.py` and `tools/make_spy_video.py` (fonttools,
cairosvg and ffmpeg); the exact commands are at the top of each script.
In the spy animations amber is always the watcher and green is Unseenet.

The logo is licensed under CC BY 4.0, see [LICENSE.md](LICENSE.md).
