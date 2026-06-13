"""
find_flags.py — Cherche des noms de flags par motif et affiche leur hash CRC32.

Sert à énumérer une catégorie (tours, bêtes, quêtes...) une fois que tu connais
le mot-clé, et à récupérer le hash pour croiser avec un diff de save.

    python find_flags.py flag_names.txt "Tower"
    python find_flags.py flag_names.txt "Remains|Beast"
    python find_flags.py flag_names.txt "^Clear_Dungeon\\d+$" --limit 200
"""
from __future__ import annotations

import argparse
import re
import zlib
from pathlib import Path


def flag_id(name: str) -> int:
    return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF


def main() -> None:
    ap = argparse.ArgumentParser(description="Recherche de flags par motif.")
    ap.add_argument("names", type=Path)
    ap.add_argument("pattern", help="regex (insensible à la casse)")
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()

    rx = re.compile(args.pattern, re.I)
    lines = args.names.read_text(encoding="utf-8", errors="ignore").splitlines()
    matches = sorted({ln.strip() for ln in lines if ln.strip() and rx.search(ln)})

    print(f"[*] {len(matches)} flags matchent /{args.pattern}/")
    for name in matches[:args.limit]:
        print(f"    0x{flag_id(name):08X}  {name}")
    if len(matches) > args.limit:
        print(f"    ... (+{len(matches) - args.limit}, augmente --limit)")


if __name__ == "__main__":
    main()
