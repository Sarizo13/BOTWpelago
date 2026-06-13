"""
scaffold_locations.py — Génère locations.json unifié (sanctuaires + tours).

Lit flag_names.txt pour les flags, dungeon_names.json / location_marker.json
(extract_msg_names) pour les noms, et produit un locations.json avec catégorie,
flag de détection, hash, AP id, et nom.

Plages d'AP ids :
  - sanctuaires : 6_081_000 + dungeon_id        (Clear_Dungeon{NNN})
  - tours       : 6_081_300 + numéro de tour    (MapTower_{NN})
  - bêtes div.  : 6_081_201..204 (déjà câblées dans BotWClient.py — ajout après confirmation des flags)

    python scaffold_locations.py --names flag_names.txt ^
        --dungeon-names data\\dungeon_names.json ^
        --location-names data\\location_marker.json ^
        --out data\\locations.json
"""
from __future__ import annotations

import argparse
import json
import re
import zlib
from pathlib import Path

SHRINE_BASE = 6_081_000
BEAST_BASE = 6_081_200   # +1..4 (cohérent avec BotWClient._is_goal_complete)
TOWER_BASE = 6_081_300

# Bêtes divines : mapping fixe (4), flags Clear_Remains{Element} confirmés par grep.
BEASTS = [
    ("Clear_RemainsWind",     "Divine Beast Vah Medoh",   "Tabantha / Rito Village"),
    ("Clear_RemainsFire",     "Divine Beast Vah Rudania", "Eldin / Goron City"),
    ("Clear_RemainsWater",    "Divine Beast Vah Ruta",    "Lanayru / Zora's Domain"),
    ("Clear_RemainsElectric", "Divine Beast Vah Naboris", "Gerudo / Gerudo Town"),
]


def flag_id(name: str) -> int:
    return zlib.crc32(name.encode("ascii")) & 0xFFFFFFFF


def load_json(p: Path | None) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() else {}


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold locations.json (sanctuaires + tours).")
    ap.add_argument("--names", required=True, type=Path, help="flag_names.txt")
    ap.add_argument("--dungeon-names", type=Path, default=None, help="dungeon_names.json")
    ap.add_argument("--location-names", type=Path, default=None, help="location_marker.json")
    ap.add_argument("--out", default=Path("locations.json"), type=Path)
    args = ap.parse_args()

    text = args.names.read_text(encoding="utf-8", errors="ignore")
    dnames = load_json(args.dungeon_names)
    lnames = load_json(args.location_names)

    existing: dict[str, dict] = {}
    if args.out.exists():
        try:
            for e in json.loads(args.out.read_text(encoding="utf-8")):
                existing[e.get("flag_name")] = e
        except Exception:
            pass

    entries: list[dict] = []

    # Sanctuaires : Clear_Dungeon{NNN}
    for n in sorted({int(m.group(1))
                     for m in re.finditer(r"^Clear_Dungeon(\d+)$", text, re.M)}):
        flag, key = f"Clear_Dungeon{n:03d}", f"Dungeon{n:03d}"
        prev = existing.get(flag) or {}
        entries.append({
            "category": "shrine",
            "flag_name": flag,
            "flag_hash": f"0x{flag_id(flag):08X}",
            "ap_id": SHRINE_BASE + n,
            "name": dnames.get(key) or prev.get("name", ""),
            "monk": dnames.get(f"{key}_master", ""),
            "region": prev.get("region", ""),
        })

    # Tours : MapTower_{NN} (bool nu uniquement, pas les _Open*/_Info/_Demo)
    for n in sorted({int(m.group(1))
                     for m in re.finditer(r"^MapTower_(\d+)$", text, re.M)}):
        flag, key = f"MapTower_{n:02d}", f"Tower{n:02d}"
        prev = existing.get(flag) or {}
        entries.append({
            "category": "tower",
            "flag_name": flag,
            "flag_hash": f"0x{flag_id(flag):08X}",
            "ap_id": TOWER_BASE + n,
            "name": lnames.get(key) or prev.get("name", ""),
            "region": prev.get("region", ""),
        })

    # Bêtes divines : Clear_Remains{Element} (mapping fixe)
    present = {ln.strip() for ln in text.splitlines()}
    for i, (flag, name, region) in enumerate(BEASTS, start=1):
        if flag not in present:
            print(f"[!] flag bête absent de flag_names.txt : {flag}")
        prev = existing.get(flag) or {}
        entries.append({
            "category": "beast",
            "flag_name": flag,
            "flag_hash": f"0x{flag_id(flag):08X}",
            "ap_id": BEAST_BASE + i,
            "name": prev.get("name") or name,
            "region": prev.get("region") or region,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    by_cat: dict[str, int] = {}
    for e in entries:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + 1
    named = sum(1 for e in entries if e["name"])
    print(f"[*] {len(entries)} locations -> {args.out}  {by_cat}")
    print(f"[*] {named}/{len(entries)} nommées")

    print("\n[*] sanctuaires + tours + bêtes câblés. Reste : quêtes (one-by-one via diff) "
          "et l'injection d'items.")


if __name__ == "__main__":
    main()
