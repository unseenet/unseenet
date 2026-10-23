"""Make src/unseenet/emoji.json from gemoji's database (UN-RFC 0031 section 5.2).

The shortcode table (every alias, so :+1: and :thumbsup: both work) plus, for
pickers (#362), the categories in gemoji's order with one shortcode per emoji,
and each one's name: description, tags and its other aliases, as search words.

    curl -sLo /tmp/gemoji.json \
      https://raw.githubusercontent.com/github/gemoji/v4.1.0/db/emoji.json
    python tools/emoji_data.py /tmp/gemoji.json

gemoji: MIT licence, (c) GitHub, Inc.
"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "unseenet" / "emoji.json"
VERSION = "gemoji-4.1.0"


def build(db: list[dict]) -> dict:
    table: dict[str, str] = {}
    categories: dict[str, list[str]] = {}
    names: dict[str, str] = {}
    for e in db:
        aliases = e.get("aliases") or []
        if not aliases:
            continue
        for a in aliases:
            table[a] = e["emoji"]
        categories.setdefault(e["category"], []).append(aliases[0])
        words = " ".join([e.get("description", "")] + (e.get("tags") or []) + aliases[1:]).lower()
        names[aliases[0]] = " ".join(dict.fromkeys(words.split()))
    return {"source": "gemoji v4.1.0 (github/gemoji, MIT licence), db/emoji.json aliases",
            "version": VERSION, "emoji": dict(sorted(table.items())),
            "categories": [{"name": k, "codes": v} for k, v in categories.items()],
            "names": names}


def main(src: str) -> None:
    data = build(json.loads(Path(src).read_text("utf-8")))
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")
    print(f"{OUT}: {len(data['emoji'])} shortcodes, {len(data['names'])} emoji in "
          f"{len(data['categories'])} categories")


if __name__ == "__main__":
    main(sys.argv[1])
