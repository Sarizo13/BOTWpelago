"""
build_loot_table — régénère la section filler_items des deux gate_items.json à partir de
data/botw_items.json (ingrédients) + une liste curée de "specials".

Objectif (demande user) : distribuer des quantités RAISONNABLES et DIFFÉRENTES, et une
bonne variété d'items. Chaque ingrédient reçoit :
  - une quantité (amount) basée sur sa famille + variation déterministe par nom,
  - un poids (count) faible (rare individuellement, varié collectivement).
Spirit Orb reste l'item dominant (count élevé). Les sections items/goal sont préservées.

Usage : python tools/build_loot_table.py
"""
from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
GATE_FILES = [PROJECT / "data" / "gate_items.json",
              PROJECT / "worlds" / "botw" / "data" / "gate_items.json"]
ITEMS_DB = PROJECT / "data" / "botw_items.json"
POUCH_DB = PROJECT / "data" / "pouch_db.json"          # types armes/armures (ActorInfo)
NAMES    = PROJECT / "tmp" / "botw_names.json"          # noms anglais (build-time, non commité)

INGREDIENT_BASE_ID = 6_080_200   # plage dédiée aux fillers ingrédients
GEAR_BASE_ID       = 6_080_600   # plage dédiée aux armes/arcs/boucliers

# armes/arcs/boucliers de BASE (numérotés 0xx) — exclut test (5xx)/amiibo/DLC. type poche 0/1/3.
_GEAR_RE = re.compile(r"^Weapon_(Sword|Lsword|Spear|Bow|Shield)_0\d\d$")
_GEAR_EXCLUDE = {"Weapon_Sword_070", "Weapon_Sword_071", "Weapon_Sword_072", "Weapon_Sword_073"}  # Master Sword & co (gate)

# quantité de base par famille (amount = base + variation déterministe 0..2)
FAMILY_AMOUNT = {
    "Fruit": 3, "Mushroom": 3, "PlantGet": 3, "Meat": 2, "FishGet": 2,
    "Ore": 4, "InsectGet": 2, "Material": 1, "Enemy": 3,
}

# specials curés (gardés/retravaillés) — count = poids dans le tirage pondéré du pool
SPECIALS = [
    {"name": "Spirit Orb", "ap_item_id": 6080100, "count": 25,   # moins dominant (loot diversifié)
     "inject": [{"type": "add_porch", "item": "Obj_DungeonClearSeal", "amount": 1},
                {"type": "add_s32", "flag": "DungeonClearSealNum", "amount": 1}]},
    {"name": "Arrows x10", "ap_item_id": 6080120, "count": 10,
     "inject": {"type": "add_porch", "item": "NormalArrow", "amount": 10}},
    {"name": "Bomb Arrows x5", "ap_item_id": 6080121, "count": 5,
     "inject": {"type": "add_porch", "item": "BombArrow_A", "amount": 5}},
    {"name": "Fire Arrows x5", "ap_item_id": 6080122, "count": 4,
     "inject": {"type": "add_porch", "item": "FireArrow", "amount": 5}},
    {"name": "Ice Arrows x5", "ap_item_id": 6080123, "count": 4,
     "inject": {"type": "add_porch", "item": "IceArrow", "amount": 5}},
    {"name": "Shock Arrows x5", "ap_item_id": 6080124, "count": 4,
     "inject": {"type": "add_porch", "item": "ElectricArrow", "amount": 5}},
    # Rubis RETIRÉS du pool (V1) : l'adresse rubis trouvée est un MIROIR que le jeu réécrit → les
    # rubis livrés disparaissent ("ajouté puis supprimé"). À restaurer en V1.1 (vrai portefeuille).
]


def amount_for(actor: str) -> int:
    family = actor.split("_")[1] if "_" in actor else ""
    base = FAMILY_AMOUNT.get(family, 2)
    var = zlib.crc32(actor.encode()) % 3   # 0..2 -> quantités différentes par item
    return max(1, base + var - 1)


def main() -> None:
    db = json.loads(ITEMS_DB.read_text(encoding="utf-8"))["items"]

    filler = list(SPECIALS)
    used_names = {f["name"] for f in filler}
    next_id = INGREDIENT_BASE_ID
    n_ing = 0
    for actor in sorted(db):
        display = db[actor]["name"]
        if display in used_names:        # noms AP doivent être uniques
            continue
        used_names.add(display)
        filler.append({
            "name": display,
            "ap_item_id": next_id,
            "count": 1,                  # poids faible -> rare individuellement, varié au global
            "inject": {"type": "add_porch", "item": actor, "amount": amount_for(actor)},
        })
        next_id += 1
        n_ing += 1

    # ── armes / arcs / boucliers (base game) — amount = durabilité (value du nœud) ──
    n_gear = 0
    if POUCH_DB.is_file() and NAMES.is_file():
        pouch = json.loads(POUCH_DB.read_text(encoding="utf-8"))
        names = json.loads(NAMES.read_text(encoding="utf-8"))
        gid = GEAR_BASE_ID
        for actor in sorted(pouch):
            if actor in _GEAR_EXCLUDE or not _GEAR_RE.match(actor):
                continue
            info = pouch[actor]
            if info.get("type") not in (0, 1, 3):
                continue
            display = names.get(actor)
            if not display or display in used_names:
                continue
            used_names.add(display)
            filler.append({
                "name": display,
                "ap_item_id": gid,
                "count": 1,
                "inject": {"type": "add_porch", "item": actor, "amount": int(info.get("life", 20))},
            })
            gid += 1
            n_gear += 1

    for gate_path in GATE_FILES:
        data = json.loads(gate_path.read_text(encoding="utf-8"))
        data["filler_items"] = filler
        gate_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  écrit {gate_path}  ({len(filler)} fillers : {len(SPECIALS)} specials + "
              f"{n_ing} ingrédients + {n_gear} armes/arcs/boucliers)")

    # aperçu quantités variées
    print("\nAperçu quantités:")
    for f in filler[8:14]:
        print(f"  {f['name']:22s} {f['inject']['item']:18s} x{f['inject']['amount']}")


if __name__ == "__main__":
    main()
