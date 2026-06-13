"""
Test de l'API live ajoutee a CemuMemoryBridge (attach() + live_*).

PowerShell admin + Cemu in-game :
    python tools/test_live_inventory_api.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

TARGET_ITEM = "Item_Ore_B"
DELTA = 10


def main():
    print("=== Test API live inventory ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return

    print(f"gd_base = 0x{br._gd_base:012X}")
    print(f"has_live_inventory = {br.has_live_inventory}")
    if br._rupees_addr:
        print(f"rupees_addr = 0x{br._rupees_addr:012X}")
    if br._inv_base:
        print(f"inv_base = 0x{br._inv_base:012X}")

    if not br.has_live_inventory:
        print("\nInventaire live non trouve.")
        br.detach()
        return

    print(f"\nRupees actuels = {br.live_get_rupees()}")

    qty = br.live_get_item_qty(TARGET_ITEM)
    print(f"{TARGET_ITEM} qty actuelle = {qty}")

    new_qty = br.live_add_item_qty(TARGET_ITEM, DELTA)
    print(f"Apres +{DELTA} -> {new_qty}")
    print(">>> Verifie en jeu (ferme/rouvre l'inventaire) <<<")

    try:
        input("ENTREE pour restaurer... ")
    except Exception:
        pass

    restored = br.live_add_item_qty(TARGET_ITEM, -DELTA)
    print(f"Restaure -> {restored}")

    br.detach()


if __name__ == "__main__":
    main()
