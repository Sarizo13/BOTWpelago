"""
Test Tips Flag Live — verifie si ecrire un flag GameData (gd_base, deja localise)
pendant le jeu (hors menu/titre) declenche immediatement le popup "Tips" natif
correspondant (EventFlow/Tips*.bfevfl), ou si ca necessite un reload de save.

Flag teste: IsGet_AncientArrow (TipsItem.bfevfl -> Demo_TipsDisplayOK si =1).
Choisi car probablement =0 chez la plupart des joueurs et purement cosmetique
(popup "tip"), donc reversible sans risque.

Usage (PowerShell admin, Cemu en jeu, PAS au menu titre):
    python tools/test_tips_flag_live.py
    python tools/test_tips_flag_live.py --revert
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge

FLAG = "IsGet_AncientArrow"


def main():
    revert = "--revert" in sys.argv
    print("=== Test Tips Flag Live ===\n")
    br = CemuMemoryBridge()
    if not br.attach():
        print("ERREUR: admin requis / Cemu introuvable.")
        return

    before = br.read_flag(FLAG)
    print(f"{FLAG} avant = {before}")

    target = 0 if revert else 1
    ok = br.write_flag(FLAG, target)
    print(f"write_flag({FLAG}, {target}) -> {ok}")

    after = br.read_flag(FLAG)
    print(f"{FLAG} apres (relu) = {after}")

    if not revert:
        print("\n--> Observe le jeu MAINTENANT (sans bouger de menu/recharger).")
        print("    Si un popup 'Tips' (bandeau bas d'ecran) apparait dans les")
        print("    secondes qui suivent => le checker Tips lit bien gd_base en live.")
        print("    Si rien -> relance avec --revert pour remettre a 0, et on")
        print("    saura que gd_base n'est pas la table lue en live par Tips.")
    else:
        print("\nFlag remis a 0 (si possible).")

    br.detach()


if __name__ == "__main__":
    main()
