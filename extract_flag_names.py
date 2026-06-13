"""
extract_flag_names.py — Extrait tous les noms de flags depuis Bootup.pack (oead).

Ouvre Bootup.pack (SARC), trouve gamedata.ssarc / savedataformat.ssarc à
l'intérieur, les décompresse (yaz0) et parse chaque BYML pour récupérer tous les
"DataName". Vérifie au passage la recette CRC32 contre les "HashValue" embarqués.

    pip install oead
    python extract_flag_names.py --bootup "...\\content\\Pack\\Bootup.pack" --out flag_names.txt
"""
from __future__ import annotations

import argparse
import sys
import zlib
from pathlib import Path

try:
    import oead
except ImportError:
    sys.exit("oead requis :  pip install oead")


def _decompress(data) -> bytes:
    data = bytes(data)
    return bytes(oead.yaz0.decompress(data)) if data[:4] == b"Yaz0" else data


def _is_map(n) -> bool:
    return hasattr(n, "items") and callable(getattr(n, "items"))


def _is_seq(n) -> bool:
    return hasattr(n, "__iter__") and not isinstance(n, (str, bytes, bytearray))


def _collect(node, names: set, hashes: dict) -> None:
    if _is_map(node):
        d = dict(node.items())
        name = d.get("DataName")
        if isinstance(name, str):
            names.add(name)
            hv = d.get("HashValue")
            if isinstance(hv, int):
                hashes[name] = hv & 0xFFFFFFFF
        for v in d.values():
            _collect(v, names, hashes)
    elif _is_seq(node):
        for v in node:
            _collect(v, names, hashes)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extracteur de noms de flags BotW.")
    ap.add_argument("--bootup", required=True, type=Path, help="chemin vers Bootup.pack")
    ap.add_argument("--out", default=Path("flag_names.txt"), type=Path)
    args = ap.parse_args()

    if not args.bootup.exists():
        sys.exit(f"introuvable : {args.bootup}")

    sarc = oead.Sarc(args.bootup.read_bytes())
    targets = [f.name for f in sarc.get_files()
               if f.name.lower().endswith(".ssarc")
               and ("savedataformat" in f.name.lower() or "gamedata" in f.name.lower())]
    if not targets:
        sys.exit("aucun gamedata/savedataformat dans Bootup.pack — mauvais pack ?")

    names: set[str] = set()
    hashes: dict[str, int] = {}
    for t in targets:
        try:
            raw = _decompress(sarc.get_file(t).data)
            if raw[:4] != b"SARC":
                print(f"  ({t}: pas un SARC, ignoré)")
                continue
            inner = oead.Sarc(raw)
        except Exception as e:
            print(f"  ({t}: ignoré — {type(e).__name__})")
            continue
        for sub in inner.get_files():
            try:
                doc = oead.byml.from_binary(_decompress(sub.data))
            except Exception:
                continue
            _collect(doc, names, hashes)
        print(f"  {t}: cumul {len(names)} noms")

    if hashes:
        bad = sum(1 for n, hv in hashes.items()
                  if (zlib.crc32(n.encode("ascii")) & 0xFFFFFFFF) != hv)
        print(f"[*] vérif recette CRC32 : {len(hashes) - bad}/{len(hashes)} "
              f"HashValue == crc32(nom)")

    args.out.write_text("\n".join(sorted(names)), encoding="utf-8")
    print(f"[*] {len(names)} noms écrits -> {args.out}")


if __name__ == "__main__":
    main()
