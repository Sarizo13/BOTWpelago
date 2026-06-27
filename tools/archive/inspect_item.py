"""
inspect_item — dump l'état live de certains items (valeur, doublons, champs candidats).

Cherche flint (Item_Ore_I) et spirit orb (Obj_DungeonClearSeal) — et tout nœud au
nom vide mais type valide (= doublon/fantôme). Affiche plusieurs offsets candidats
pour comprendre la quantité affichée.

Usage : python tools/inspect_item.py
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

TARGETS = ("Item_Ore_I", "Obj_DungeonClearSeal")


def main() -> None:
    br = CemuMemoryBridge()
    if not br.attach():
        print("Échec attach.")
        return
    nodes = br._scan_pouch_nodes()
    print(f"{len(nodes)} nœuds. Offsets: type@0x{br._NODE_OFF_TYPE:X} "
          f"value@0x{br._NODE_OFF_VAL:X} sub@0x{br._NODE_OFF_SUB:X}\n")

    def dump(n, why):
        r = n["raw"]
        val = struct.unpack_from(">i", r, br._NODE_OFF_VAL)[0]
        # autres champs 4o candidats pour la quantité/équip
        cands = {hex(o): struct.unpack_from(">i", r, o)[0]
                 for o in (0x18, 0x6C, 0x70, 0x80, 0x84)}
        print(f" [{why}] slot{n['slot']} host=0x{n['host']:012X} '{n['name']}' "
              f"type={n['type']} sub={n['sub']} value={val}")
        print(f"        candidats={cands}")

    for n in nodes:
        if n["name"] in TARGETS:
            dump(n, "CIBLE")
    print("--- doublons / fantômes (nom vide mais type != libre) ---")
    for n in nodes:
        if not n["name"] and n["type"] not in (0xFFFFFFFF,) and n["type"] < 0x20:
            dump(n, "FANTOME")
    # compte par nom pour repérer doublons
    from collections import Counter
    names = Counter(n["name"] for n in nodes if n["name"])
    dups = {k: v for k, v in names.items() if v > 1}
    print("doublons par nom :", dups or "aucun")
    br.detach()


if __name__ == "__main__":
    main()
