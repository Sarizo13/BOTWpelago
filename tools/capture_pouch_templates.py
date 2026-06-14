"""
capture_pouch_templates — alimente le cache local de templates PouchItem.

À lancer UNE FOIS pendant que Cemu tourne avec une save qui contient des items
(idéalement des matériaux, type 7). Capture un nœud-template propre par type et
l'écrit dans ~/.botwpelago/pouch_templates.json. Ce cache permet ensuite à
`live_create_item` de créer ces types d'items même sur une save vide.

Usage : python tools/capture_pouch_templates.py
"""
from __future__ import annotations

from BotWClient.memory_injector import CemuMemoryBridge


def main() -> None:
    bridge = CemuMemoryBridge()
    if not bridge.attach():
        print("Échec : Cemu introuvable ou inventaire live non localisé "
              "(lance Cemu + BotW, en admin si Cemu l'est).")
        return
    # attach() appelle déjà _auto_capture_templates(); on affiche le résultat.
    types = sorted(int(k) for k in bridge._templates)
    if types:
        print(f"Templates en cache (types) : {types}")
        print(f"Fichier : {bridge._template_store}")
        if 7 not in types:
            print("⚠ Aucun template type=7 (matériaux). Récupère un matériau "
                  "(pomme, champignon, corne…) puis relance pour couvrir ce type.")
    else:
        print("Aucun template capturé (inventaire vide ?). Récupère quelques items "
              "puis relance.")
    bridge.detach()


if __name__ == "__main__":
    main()
