"""
build_item_db — construit data/botw_items.json (base d'items de poche pour AP) à partir
de botw_names.json (mapping nom interne -> nom anglais, par MrCheeze :
https://github.com/MrCheeze/botw-tools — utilisé comme source, non redistribué).

On ne garde que les INGRÉDIENTS (PouchItemType 7 = Material) : fruits, champignons,
plantes, minerais, viande, poisson, insectes, parts de monstres, matériaux. Ce sont les
items que live_create_item gère de façon fiable (icône pilotée par le nom, pas de données
de recette comme les plats cuisinés).

Usage : python tools/build_item_db.py [chemin botw_names.json]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "tmp" / "botw_names.json"
DST = PROJECT / "data" / "botw_items.json"

# Préfixes d'ingrédients -> tous PouchItemType 7 (Material), sous-type 8 (ingrédient simple)
MATERIAL_PREFIXES = (
    "Item_Fruit_", "Item_Mushroom_", "Item_PlantGet_", "Item_Ore_",
    "Item_Meat_", "Item_FishGet_", "Item_InsectGet_", "Item_Material_",
    "Item_Enemy_",
)


def main() -> None:
    names = json.loads(SRC.read_text(encoding="utf-8"))
    items: dict[str, dict] = {}
    for actor, display in sorted(names.items()):
        if not actor.startswith(MATERIAL_PREFIXES):
            continue
        # exclure les variantes d'affichage (ex: "..._00" -> "X x[NUMBER]")
        if "[" in display or display.endswith("]"):
            continue
        items[actor] = {"name": display, "type": 7, "sub": 8}

    out = {
        "_comment": ("Base d'items de poche AP (ingrédients type 7). Noms anglais issus de "
                     "MrCheeze/botw-tools (botw_names.json). Généré par tools/build_item_db.py."),
        "items": items,
    }
    DST.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(items)} ingrédients -> {DST}")
    # aperçu
    for a in list(items)[:6]:
        print(f"  {a} -> {items[a]['name']}")


if __name__ == "__main__":
    main()
