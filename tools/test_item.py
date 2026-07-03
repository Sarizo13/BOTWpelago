"""
test_item — DIAGNOSTIC. Attache Cemu/BotW et LIVRE un item directement en mémoire live
(via live_create_item), SANS passer par Archipelago ni régénérer de seed. Idéal pour tester
l'injection d'un type précis (ex: bouclier en catégorie vide).

Type / sub (ItemUse) / durabilité sont tirés de data/pouch_db.json.

Usage :
  python tools/test_item.py Weapon_Shield_018
  python tools/test_item.py Weapon_Shield_018 Weapon_Bow_027 Weapon_Sword_024
  python tools/test_item.py Weapon_Shield_018 --value 30     # forcer la durabilité (life)

Puis, en jeu, ouvre/ferme l'inventaire (page boucliers) pour le redessin.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

POUCH_DB = PROJECT / "data" / "pouch_db.json"
_TYPE_NAME = {0: "Arme", 1: "Arc", 2: "Fleche", 3: "Bouclier", 4: "Armure-tete",
              5: "Armure-torse", 6: "Armure-jambes", 7: "Materiau", 8: "Nourriture", 9: "Objet-cle"}


def main() -> None:
    ap = argparse.ArgumentParser(description="Livre un item live dans la poche BotW (test).")
    ap.add_argument("actors", nargs="+", help="noms d'acteurs (ex: Weapon_Shield_018)")
    ap.add_argument("--value", type=int, default=None,
                    help="durabilité (life) / quantité à forcer ; sinon depuis pouch_db")
    args = ap.parse_args()

    db = json.loads(POUCH_DB.read_text(encoding="utf-8")) if POUCH_DB.is_file() else {}

    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché (lance le jeu + charge la save).")
        return
    if not b.has_live_inventory:
        print("ERREUR: inventaire live non localisé.")
        return

    for actor in args.actors:
        info = db.get(actor)
        if info is None:
            print(f"[SKIP] {actor} : absent de pouch_db.json (type/sub inconnus).")
            continue
        typ = int(info.get("type", 7))
        sub = info.get("sub")
        val = args.value if args.value is not None else int(info.get("life", 1))
        ok = b.live_create_item(actor, typ, sub, val)
        tn = _TYPE_NAME.get(typ, "?")
        print(f"[{'OK ' if ok else 'ECHEC'}] {actor}  ({tn}, type={typ} sub={sub} val={val})")

    print("\n→ En jeu : ouvre/ferme l'inventaire sur la bonne page pour le redessin.")


if __name__ == "__main__":
    main()
