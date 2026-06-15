"""
Test live_add_rupees / live_get_rupees.

PowerShell admin + Cemu in-game :
    python tools/test_live_rupees.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

DELTA = 100


def main():
    print("=== Test live rupees ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return

    if not br.has_live_inventory:
        print("Inventaire live non trouve.")
        br.detach()
        return

    before = br.live_get_rupees()
    print(f"Rupees avant = {before}")

    after = br.live_add_rupees(DELTA)
    print(f"Apres +{DELTA} -> {after}")
    print(">>> Regarde le compteur de rubis EN JEU (devrait etre instantane) <<<")

    try:
        input("ENTREE pour restaurer... ")
    except Exception:
        pass

    restored = br.live_add_rupees(-DELTA)
    print(f"Restaure -> {restored}")

    br.detach()


if __name__ == "__main__":
    main()
