"""
build_sort_keys — extrait le `sortKey` de chaque objet de poche depuis ActorInfo.product.sbyml
du dump (via le chemin BasePath de la config BOTWpelago) → data/item_sort_keys.json.

Le pouch de BotW trie les items par `sortKey` (au sein de chaque catégorie). Pour insérer un
NOUVEL item live à la bonne place (sans désorganiser l'inventaire = crash), le client ancre après
le dernier nœud dont le sortKey ≤ celui du nouvel item. Ce fichier fournit la table {nom: sortKey}.

Usage : python tools/build_sort_keys.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from botwpelago.config import Config  # noqa: E402

OUT = PROJECT / "data" / "item_sort_keys.json"
# préfixes d'objets pouch (matériaux, armes, arcs, boucliers, armures, objets-clés, nourriture…)
_KEEP = ("Item_", "Weapon_", "Bow_", "Arrow", "Shield_", "Armor_", "Obj_", "Animal_", "Get_", "PlayerStole")


def main() -> None:
    import oead
    cfg = Config.load()
    base = cfg.game_base_path
    if not base:
        print("ERREUR: game_base_path vide dans ~/.botwpelago/config.json")
        sys.exit(1)
    ai = Path(base) / "Actor" / "ActorInfo.product.sbyml"
    if not ai.is_file():
        print(f"ERREUR: ActorInfo introuvable : {ai}")
        sys.exit(1)
    byml = oead.byml.from_binary(oead.yaz0.decompress(ai.read_bytes()))
    keys: dict[str, int] = {}
    for a in byml["Actors"]:
        try:
            name = str(a["name"])
            sk = int(a["sortKey"])
        except Exception:
            continue
        if name.startswith(_KEEP):
            keys[name] = sk
    OUT.write_text(json.dumps(keys, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    print(f"  écrit {OUT}  ({len(keys)} sortKeys)")


if __name__ == "__main__":
    main()
