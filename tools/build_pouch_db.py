"""
build_pouch_db — base COMPLÈTE des objets de poche (armes, arcs, boucliers, armures, matériaux)
depuis ActorInfo.product.sbyml du dump → data/pouch_db.json.

Donne au client, pour CHAQUE objet : son PouchItemType (pour l'injection live), sa durabilité
(armes), sa sortKey (placement trié) et son nom anglais (botw_names.json, MrCheeze — non redistribué,
utilisé comme source). Complète data/pouch_items.json (curé) via _load_pouch_items.

Type de poche déduit du `profile` ActorInfo :
  WeaponSmallSword/LargeSword/Spear/OptionalWeapon -> 0 (arme mêlée)
  WeaponBow -> 1 · WeaponShield -> 3 · ArmorHead -> 4 · ArmorUpper -> 5 · ArmorLower -> 6
  Item_* (matériaux) -> 7

Usage : python tools/build_pouch_db.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from botwpelago.config import Config  # noqa: E402

OUT = PROJECT / "data" / "pouch_db.json"

_PROFILE_TYPE = {
    "WeaponSmallSword": 0, "WeaponLargeSword": 0, "WeaponSpear": 0, "OptionalWeapon": 0,
    "WeaponBow": 1, "WeaponShield": 3,
    "ArmorHead": 4, "ArmorUpper": 5, "ArmorLower": 6,
}


def main() -> None:
    import oead
    base = Config.load().game_base_path
    ai = Path(base) / "Actor" / "ActorInfo.product.sbyml"
    if not ai.is_file():
        print(f"ERREUR: ActorInfo introuvable : {ai}")
        sys.exit(1)
    byml = oead.byml.from_binary(oead.yaz0.decompress(ai.read_bytes()))
    out: dict[str, dict] = {}
    for a in byml["Actors"]:
        try:
            name = str(a["name"])
            profile = str(a["profile"])
        except Exception:
            continue
        # type de poche : armes/armures via profil ; matériaux via préfixe Item_
        if profile in _PROFILE_TYPE:
            typ = _PROFILE_TYPE[profile]
            sub = 0
        elif name.startswith("Item_"):
            typ, sub = 7, 8
        else:
            continue
        entry: dict = {"type": typ, "sub": sub}
        try:
            entry["sortKey"] = int(a["sortKey"])
        except Exception:
            pass
        if typ in (0, 1, 3):                       # armes/arcs/boucliers : durabilité
            try:
                entry["life"] = int(a["generalLife"])
            except Exception:
                pass
        # NB: on NE stocke PAS le nom anglais (botw_names = tiers non redistribué) → data commitable.
        out[name] = entry
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    from collections import Counter
    c = Counter(v["type"] for v in out.values())
    print(f"  écrit {OUT}  ({len(out)} objets)  types={dict(sorted(c.items()))}")


if __name__ == "__main__":
    main()
