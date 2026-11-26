#!/usr/bin/env python3
"""Print the "Export for agents" routing table for a page hash, without a browser.

Runs the script embedded in index.html under Node, so the output matches the page's export dialog
exactly (same data, same functions). Needs `node` on PATH.

Run:  python3 -I scripts/export.py --hash '#e-abc12-def34' [--format md|json] [--page index.html]
      No --hash: the page's default picks.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DRIVER = r"""
const A = globalThis.__arena;
const [hash, fmt] = process.argv.slice(2);
const SP = A.decode(A.DATA);
const h = A.decodeHash(hash);
if (hash && !h) { console.error("not a page hash: " + hash); process.exit(2); }
const fam = !!(h && h.fam), sc = h ? h.sc : true;
const S = fam ? SP.F : SP.E;
let sel = h ? A.resolveIds(SP, h.ids, fam) : [];
if (!sel.length) sel = A.resolveIds(SP, A.presetDefault(SP.E).map(i => SP.E.models[i].id), fam);
const X = A.exportData(SP, S, sel, sc, {});
process.stdout.write(fmt === "json" ? A.exportJSON(X) : A.exportMarkdown(X));
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hash", default="", help="selection hash from the page URL, e.g. '#e-abc12-def34'")
    ap.add_argument("--format", choices=["md", "json"], default="md")
    ap.add_argument("--page", type=Path, default=ROOT / "index.html")
    args = ap.parse_args()

    node = shutil.which("node")
    if not node:
        print("node not found on PATH; it runs the page's own export code", file=sys.stderr)
        return 1
    html = args.page.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    if not scripts or "__arena" not in scripts[-1]:
        print(f"no Arena Matchup script found in {args.page}; run ./refresh.sh first", file=sys.stderr)
        return 1
    res = subprocess.run([node, "-", args.hash, args.format], input=scripts[-1] + "\n" + DRIVER,
                         text=True, capture_output=True)
    sys.stdout.write(res.stdout)
    sys.stderr.write(res.stderr)
    return res.returncode


if __name__ == "__main__":
    sys.exit(main())
