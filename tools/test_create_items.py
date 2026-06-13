"""
Test de la methode de PRODUCTION CemuMemoryBridge.live_create_item (insertion live
d'un nouvel item) sur plusieurs items, via la table de loot data/pouch_items.json.

Cree quelques items type-7 (duplicats OK pour le test) pour valider le multi-insert.
Lecture+ecriture. Usage (admin, Cemu en jeu) :
    python tools/test_create_items.py
"""
import sys
import json
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

LOOT = json.loads((Path(__file__).parents[1] / "data" / "pouch_items.json").read_text(encoding="utf-8"))["items"]

# 3 items du loot a creer (val = quantite)
TESTS = [
    ("Item_Fruit_J",   3),
    ("Item_FishGet_A", 5),
    ("Item_Ore_C",     9),
]


def main():
    bridge = CemuMemoryBridge()
    if not bridge.attach() or not bridge.has_live_inventory:
        print("ERREUR attach / inventaire live introuvable.")
        return

    for name, qty in TESTS:
        info = LOOT.get(name, {"type": 7})
        ok = bridge.live_create_item(name, info["type"], info.get("sub"), qty)
        print(f"  live_create_item({name}, type={info['type']}, val={qty}) -> {ok}")

    print("\n-> Ouvre l'inventaire (Ingredients), verifie les 3 nouveaux items + navigation fluide.")
    print("   (rien n'est sauvegarde sur disque ; reload pour nettoyer)")


if __name__ == "__main__":
    main()
