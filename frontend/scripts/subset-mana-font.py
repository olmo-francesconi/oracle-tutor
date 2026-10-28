"""Rebuild src/fonts/mana-subset.woff2: the mana-font glyphs src/lib/manaSymbols.ts can render (~8 KB vs 187 KB).

Run from frontend/ after changing manaSymbols.ts or upgrading mana-font:
  uvx --from 'fonttools[woff]==4.60.1' python scripts/subset-mana-font.py

The class enumeration mirrors getManaClass; keep the two in sync, or a new symbol renders as a blank box.
"""

import itertools
import re
import subprocess
import sys
from pathlib import Path

SINGLES = list("wubrgcsxyztqeap")
NAMED = ["paw", "infinity", "1/2", "acorn", "tk", "100"]
SPECIAL = {"t": "tap", "q": "untap", "a": "acorn", "tk": "ticket", "paw": "paw", "s": "s", "c": "c", "e": "e",
           "infinity": "infinity", "1/2": "1-2", "100": "100", "acorn": "acorn"}
MAX_NUMERIC = 20
COMPACT_HYBRID_PARTS = "wubrg2p"


def producible_classes() -> set[str]:
    contents = set(SINGLES) | set(NAMED) | {f"{n}" for n in range(MAX_NUMERIC + 1)} | {f"{n:02d}" for n in range(10)}
    for k in (2, 3):
        contents |= {"/".join(p) for p in itertools.product([*SINGLES, "2"], repeat=k)}
        contents |= {"".join(p) for p in itertools.product(COMPACT_HYBRID_PARTS, repeat=k)}
    return {SPECIAL.get(c, c.replace("/", "")) for c in contents} | {"cost"}


def codepoints(css: str, classes: set[str]) -> set[int]:
    found = set()
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if not any(c in classes for c in re.findall(r"\.ms-([a-z0-9-]+)", selectors)):
            continue
        for value in re.findall(r'content:\s*"([^"]*)"', body):
            found |= {ord(ch) for ch in re.sub(r"\\([0-9a-fA-F]{1,6}) ?", lambda m: chr(int(m[1], 16)), value)}
    return found


def main() -> None:
    cps = codepoints(Path("src/mana-font.css").read_text(encoding="utf-8"), producible_classes())
    subprocess.run([sys.executable, "-m", "fontTools.subset", "node_modules/mana-font/fonts/mana.woff2",
                    "--unicodes=" + ",".join(f"U+{c:04X}" for c in sorted(cps)), "--flavor=woff2",
                    "--layout-features=*", "--output-file=src/fonts/mana-subset.woff2"], check=True)
    print(f"src/fonts/mana-subset.woff2: {len(cps)} glyphs")


if __name__ == "__main__":
    main()
