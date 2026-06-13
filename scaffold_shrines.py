"""
scaffold_shrines.py — Génère un shrines.json squelette depuis flag_names.txt.

Extrait tous les flags de complétion de sanctuaire (Clear_Dungeon{NNN}), calcule
leur hash, assigne un AP id stable (= base + numéro interne), et écrit un
shrines.json prêt à compléter (champs name/region vides à remplir).

Réexécutable sans perte : préserve les name/region déjà saisis si le fichier existe.

    python scaffold_shrines.py --names flag_names.txt --out data\shrines.json
"""
from __future__ import annotations

import argparse
import json
import re
import zlib
from pathlib import Path

LOCATION_BASE = 6_081_000  # doit matcher worlds/botw/locations.py

# Correspondances confirmées empiriquement (à étoffer au fil de tes captures).
KNOWN: dict[int, tuple[str, str]] = {
    38: ("Oman Au Shrine", "Great Plateau"),  # confirmé via IsGet_Obj_Magnetglove (Magnésie)
}


def flag_id(name: str) -> int:
    return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold shrines.json depuis flag_names.txt.")
    ap.add_argument("--names", required=True, type=Path, help="flag_names.txt")
    ap.add_argument("--dungeon-names", type=Path, default=None,
                    help="dungeon_names.json (extract_msg_names) pour remplir les noms")
    ap.add_argument("--out", default=Path("shrines.json"), type=Path)
    args = ap.parse_args()

    text = args.names.read_text(encoding="utf-8", errors="ignore")
    dungeons = sorted({int(m.group(1))
                       for m in re.finditer(r"^Clear_Dungeon(\d+)$", text, re.M)})
    if not dungeons:
        print("[!] aucun Clear_Dungeon* trouvé — mauvais flag_names.txt ?")
        return

    # noms autoritatifs depuis le dump (extract_msg_names)
    dnames: dict[str, str] = {}
    if args.dungeon_names and args.dungeon_names.exists():
        dnames = json.loads(args.dungeon_names.read_text(encoding="utf-8"))

    # préserver le travail manuel déjà fait (région notamment)
    existing: dict[str, dict] = {}
    if args.out.exists():
        try:
            for e in json.loads(args.out.read_text(encoding="utf-8")):
                existing[e.get("flag_name")] = e
        except Exception:
            pass

    entries = []
    for n in dungeons:
        flag = f"Clear_Dungeon{n:03d}"
        key = f"Dungeon{n:03d}"
        prev = existing.get(flag) or {}
        name = dnames.get(key) or prev.get("name") or (KNOWN[n][0] if n in KNOWN else "")
        region = prev.get("region") or (KNOWN[n][1] if n in KNOWN else "")
        entries.append({
            "dungeon_id": n,
            "flag_name": flag,
            "flag_hash": f"0x{flag_id(flag):08X}",
            "ap_id": LOCATION_BASE + n,
            "name": name,
            "monk": dnames.get(f"{key}_master", ""),
            "region": region,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    filled = sum(1 for e in entries if e["name"])
    print(f"[*] {len(entries)} sanctuaires -> {args.out}")
    print(f"[*] {filled} nommés, {len(entries) - filled} sans nom"
          + ("" if dnames else "  (passe --dungeon-names data\\dungeon_names.json)"))

    # flags non-sanctuaire de type "Clear_" + Ganon : tes bêtes divines / boss sont
    # probablement là-dedans, à câbler à la main.
    other = sorted(set(re.findall(r"^Clear_(?!Dungeon\d+$)\S+$", text, re.M)))
    ganon = sorted(set(re.findall(r"^\S*Ganon\S*$", text, re.M)))[:15]
    if other:
        print("\n[*] autres flags 'Clear_' (bêtes divines / events probables) :")
        for f in other[:40]:
            print(f"    {f}  -> 0x{flag_id(f):08X}")
    if ganon:
        print("\n[*] flags contenant 'Ganon' (objectif final possible) :")
        for f in ganon:
            print(f"    {f}  -> 0x{flag_id(f):08X}")


if __name__ == "__main__":
    main()
