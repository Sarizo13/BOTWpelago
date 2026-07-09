"""
build_loot_table — régénère la section filler_items des deux gate_items.json à partir de
data/botw_items.json (ingrédients) + une liste curée de "specials".

Objectif (demande user) : distribuer des quantités RAISONNABLES et DIFFÉRENTES, et une
bonne variété d'items. Chaque filler reçoit :
  - une quantité (amount) basée sur sa famille + variation déterministe par nom,
    plafonnée par la rareté (rare ≤ 2, epic = 1),
  - un TIER de rareté (common/uncommon/rare/epic) → poids (count) dans le tirage
    pondéré du pool : common 8, uncommon 4, rare 2, epic 1. Une arme Royal Guard
    tombe donc 8× moins souvent qu'une pomme.
Les specials (Spirit Orb, flèches) sont rescalés pour garder leur part (~15 %) du
pool total. Les sections items/goal sont préservées.

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

# ── Rareté ────────────────────────────────────────────────────────────────────
# count = poids dans le tirage pondéré de create_items (worlds/botw). Assignation
# par mots-clés (substring, sensible à la casse) sur le nom anglais affiché ;
# PREMIER match gagne → l'ordre des règles compte (epic avant rare avant common).
TIER_WEIGHTS = {"common": 8, "uncommon": 4, "rare": 2, "epic": 1}

_GEAR_TIER_RULES: list[tuple[str, tuple[str, ...]]] = [
    # uniques / amiibo / matériel de labo antique / champion
    ("epic", ("Royal Guard", "Savage Lynel", "Hylian Shield", "Bow of Light",
              "Twilight Bow", "Fierce Deity", "Goddess Sword", "Six Sages",
              "Biggoron", "Sea-Breeze", "Hero's Shield", "Boulder Breaker",
              "Scimitar of the Seven", "Great Eagle", "Lightscale", "Daybreaker",
              "Ancient Bladesaw", "Ancient Short Sword", "Ancient Spear",
              "Ancient Bow", "Ancient Shield")),
    # overrides mid-tier AVANT les familles rare/common qui les engloberaient
    ("uncommon", ("Spiked", "Silverscale")),
    ("rare", ("Royal", "Knight's", "Lynel", "Guardian", "Ancient", "Dragonbone",
              "Dragon Bone", "Silver", "Steel Lizal", "Enhanced Lizal",
              "Flameblade", "Frostblade", "Thunderblade", "Flamespear",
              "Frostspear", "Thunderspear", "Windcleaver", "Moonlight",
              "Edge of Duality", "Eightfold Longblade", "Golden", "Stone Smasher",
              "Demon Carver", "Meteor Rod", "Blizzard Rod", "Thunderstorm Rod",
              "Radiant Shield")),
    ("common", ("Traveler's", "Boko ", "Rusty", "Tree Branch", "Torch",
                "Soup Ladle", "Pot Lid", "Wooden", "Boat Oar", "Farmer's",
                "Farming", "Korok Leaf", "Hunter's", "Fisherman's", "Axe",
                "Iron Sledgehammer", "Fishing Harpoon", "Throwing Spear",
                "Bokoblin Arm", "Moblin Arm", "Lizalfos Arm")),
    # défaut gear : uncommon (Soldier, Zora, Gerudo, Forest Dweller, Lizal, Moblin…)
]

_INGREDIENT_TIER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("epic", ("Star Fragment", "Dinraal", "Naydra", "Farosh", "Diamond")),
    ("rare", ("Ruby", "Sapphire", "Topaz", "Luminous", "Guts", "Hearty", "Endura",
              "Gourmet", "Silent Princess", "Lynel", "Molduga")),
    ("uncommon", ("Fang", "Tail", "Prime", "Opal", "Amber", "Mighty", "Energetic",
                  "Courser", "Staminoka", "Stealthfin", "Smotherwing")),
    # défaut ingrédient : common (pommes, champignons, herbes, cornes…)
]

# plafond de quantité par tier (les items précieux arrivent à l'unité)
TIER_AMOUNT_CAP = {"rare": 2, "epic": 1}


def tier_for(display: str, rules: list[tuple[str, tuple[str, ...]]], default: str) -> str:
    for tier, keywords in rules:
        if any(kw in display for kw in keywords):
            return tier
    return default

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

    filler = [dict(s) for s in SPECIALS]
    used_names = {f["name"] for f in filler}
    tier_census: dict[str, int] = {t: 0 for t in TIER_WEIGHTS}
    next_id = INGREDIENT_BASE_ID
    n_ing = 0
    for actor in sorted(db):
        display = db[actor]["name"]
        if display in used_names:        # noms AP doivent être uniques
            continue
        used_names.add(display)
        tier = tier_for(display, _INGREDIENT_TIER_RULES, "common")
        tier_census[tier] += 1
        amount = min(amount_for(actor), TIER_AMOUNT_CAP.get(tier, 99))
        filler.append({
            "name": display,
            "ap_item_id": next_id,
            "count": TIER_WEIGHTS[tier],   # poids du tirage pondéré
            "tier": tier,
            "inject": {"type": "add_porch", "item": actor, "amount": amount},
        })
        next_id += 1
        n_ing += 1

    # ── armes / arcs / boucliers (base game) — amount = durabilité (value du nœud),
    #    JAMAIS plafonnée par le tier (ce n'est pas une quantité) ──
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
            tier = tier_for(display, _GEAR_TIER_RULES, "uncommon")
            tier_census[tier] += 1
            filler.append({
                "name": display,
                "ap_item_id": gid,
                "count": TIER_WEIGHTS[tier],
                "tier": tier,
                "inject": {"type": "add_porch", "item": actor, "amount": int(info.get("life", 20))},
            })
            gid += 1
            n_gear += 1

    # ── rescale des specials : ils gardent leur part relative du pool (~15 %).
    #    Avant tiers : nonspecials pesaient 1 chacun (total = N) ; maintenant total = T.
    n_nonspecial = n_ing + n_gear
    total_tiered = sum(f["count"] for f in filler[len(SPECIALS):])
    scale = (total_tiered / n_nonspecial) if n_nonspecial else 1.0
    for f in filler[:len(SPECIALS)]:
        f["count"] = max(1, round(f["count"] * scale))

    for gate_path in GATE_FILES:
        data = json.loads(gate_path.read_text(encoding="utf-8"))
        data["filler_items"] = filler
        gate_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  écrit {gate_path}  ({len(filler)} fillers : {len(SPECIALS)} specials + "
              f"{n_ing} ingrédients + {n_gear} armes/arcs/boucliers)")

    # aperçu tiers + quantités
    total = sum(f["count"] for f in filler)
    print(f"\nRépartition tiers ({n_nonspecial} items, poids total {total}, "
          f"specials ×{scale:.2f}):")
    for tier, weight in TIER_WEIGHTS.items():
        n = tier_census[tier]
        print(f"  {tier:9s} ×{weight}  : {n:3d} items  ({n * weight * 100 // total}% du tirage)")
    spec_w = sum(f["count"] for f in filler[:len(SPECIALS)])
    print(f"  specials      : {len(SPECIALS):3d} items  ({spec_w * 100 // total}% du tirage)")
    print("\nAperçu:")
    for f in filler[8:14]:
        print(f"  [{f.get('tier', '?'):8s}] {f['name']:22s} {f['inject']['item']:18s} "
              f"x{f['inject']['amount']} poids {f['count']}")


if __name__ == "__main__":
    main()
