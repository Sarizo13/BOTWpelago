"""
extract_msg_names.py — Extrait les noms lisibles depuis les fichiers message du jeu.

Lit Msg_<lang>.product.ssarc (SARC yaz0 de fichiers .msbt) et parse :
  - StaticMsg/Dungeon.msbt        -> dungeon_names.json   {DungeonNNN: "Oman Au Shrine", ...}
  - StaticMsg/LocationMarker.msbt -> location_marker.json {Tower01..15, lieux, bêtes...}

Tout vient de TON dump -> aucune dépendance externe, redistribuable avec ton projet.

    pip install oead
    python extract_msg_names.py --src "...\\content\\Pack\\Bootup_EUen.pack"

Le Msg est imbriqué dans Bootup_<lang>.pack ; le script descend dedans automatiquement.
Lister les langues dispo :
    Get-ChildItem -Recurse -Filter "Bootup_*.pack" "...\\[ALZP01]\\content"
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

try:
    import oead
except ImportError:
    sys.exit("oead requis :  pip install oead")


def _decompress(data) -> bytes:
    data = bytes(data)
    return bytes(oead.yaz0.decompress(data)) if data[:4] == b"Yaz0" else data


def parse_msbt(data: bytes) -> dict[str, str]:
    """Parse un MSBT (MsgStdBn) -> {label: texte}. Gère LBL1 + TXT2, big/little endian."""
    if data[:8] != b"MsgStdBn":
        return {}
    be = data[8:10] == b"\xfe\xff"
    e = ">" if be else "<"
    codec = "utf-16-be" if be else "utf-16-le"
    sec_count = struct.unpack_from(e + "H", data, 0x0E)[0]

    sections: dict[bytes, bytes] = {}
    pos = 0x20
    for _ in range(sec_count):
        magic = data[pos:pos + 4]
        size = struct.unpack_from(e + "I", data, pos + 4)[0]
        sections[magic] = data[pos + 16: pos + 16 + size]
        pos = (pos + 16 + size + 0xF) & ~0xF  # sections alignées 0x10

    lbl = sections.get(b"LBL1")
    txt = sections.get(b"TXT2") or sections.get(b"TXT1")
    if lbl is None or txt is None:
        return {}

    # LBL1 : table de hash -> {index TXT: label}
    idx_to_name: dict[int, str] = {}
    groups = struct.unpack_from(e + "I", lbl, 0)[0]
    for g in range(groups):
        n_labels, off = struct.unpack_from(e + "II", lbl, 4 + g * 8)
        p = off
        for _ in range(n_labels):
            ln = lbl[p]; p += 1
            name = lbl[p:p + ln].decode("ascii", "replace"); p += ln
            idx = struct.unpack_from(e + "I", lbl, p)[0]; p += 4
            idx_to_name[idx] = name

    # TXT2 : offsets puis chaînes UTF-16 terminées par NUL
    count = struct.unpack_from(e + "I", txt, 0)[0]
    offs = [struct.unpack_from(e + "I", txt, 4 + i * 4)[0] for i in range(count)]
    out: dict[str, str] = {}
    for i in range(count):
        name = idx_to_name.get(i)
        if name is None:
            continue
        start = offs[i]
        end = offs[i + 1] if i + 1 < count else len(txt)
        text = txt[start:end].decode(codec, "replace").split("\x00")[0]
        text = "".join(c for c in text if ord(c) >= 0x20)  # retire les balises de contrôle
        out[name] = text
    return out


def _find_msbts(sarc) -> dict[str, bytes]:
    """Trouve Dungeon.msbt / LocationMarker.msbt, en descendant dans un Msg_*.ssarc imbriqué si besoin."""
    wanted = {"Dungeon.msbt", "LocationMarker.msbt"}
    out: dict[str, bytes] = {}
    for f in sarc.get_files():
        if f.name.split("/")[-1] in wanted:
            out[f.name.split("/")[-1]] = bytes(f.data)
    if out:
        return out
    # message archive imbriquée dans Bootup_<lang>.pack -> descendre dans Msg_*.product.ssarc
    for f in sarc.get_files():
        nm = f.name.lower()
        if nm.endswith(".ssarc") and "msg" in nm:
            try:
                inner = oead.Sarc(_decompress(f.data))
            except Exception:
                continue
            for g in inner.get_files():
                if g.name.split("/")[-1] in wanted:
                    out[g.name.split("/")[-1]] = bytes(g.data)
            if out:
                return out
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Extracteur de noms (MSBT) BotW.")
    ap.add_argument("--src", required=True, type=Path,
                    help="Bootup_<lang>.pack OU Msg_<lang>.product.ssarc")
    ap.add_argument("--outdir", default=Path("."), type=Path)
    args = ap.parse_args()

    sarc = oead.Sarc(_decompress(args.src.read_bytes()))
    found = _find_msbts(sarc)
    wanted = {"Dungeon.msbt": "dungeon_names.json",
              "LocationMarker.msbt": "location_marker.json"}

    if not found:
        print("[!] Dungeon.msbt / LocationMarker.msbt introuvables dans ce fichier.")
        print("    Contenu (échantillon) :")
        for f in list(sarc.get_files())[:25]:
            print(f"      {f.name}")
        return

    args.outdir.mkdir(parents=True, exist_ok=True)
    for base, out_name in wanted.items():
        if base in found:
            d = parse_msbt(found[base])
            (args.outdir / out_name).write_text(
                json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"[*] {base}: {len(d)} entrées -> {out_name}")
            if base == "Dungeon.msbt":
                print(f"    validation: Dungeon038 = {d.get('Dungeon038')!r} "
                      f"(attendu 'Oman Au Shrine')")
            if base == "LocationMarker.msbt":
                towers = {k: v for k, v in d.items() if k.startswith("Tower")}
                print(f"    {len(towers)} tours (ex: {next(iter(towers.items()), None)})")


if __name__ == "__main__":
    main()
