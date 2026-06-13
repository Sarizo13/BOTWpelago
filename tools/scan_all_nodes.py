"""
Scan robuste de TOUS les noeuds PouchItem (adressage par adresse guest absolue, stable
dans la session — contrairement aux index de slot qui dependent du re-scan inv_base).

Affiche pour chaque noeud : guest addr, nom, type(+0x20C), valeur(+0x214), et si ses
pointeurs internes sont auto-referents (vrai item) ou non.

Lecture seule. Usage (PowerShell admin, Cemu en jeu) :
    python tools/scan_all_nodes.py
"""
import sys
import struct
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).parents[1]))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE

CEMU_MEM_BASE = 0x247E4440000
STRIDE = _ITEM_STRIDE


def main():
    bridge = CemuMemoryBridge()
    if not bridge.attach() or not bridge.has_live_inventory:
        print("ERREUR attach / inventaire live introuvable.")
        return
    inv = bridge._inv_base
    inv_g = inv - CEMU_MEM_BASE
    print(f"inv_base host=0x{inv:012X} guest=0x{inv_g:08X}\n")
    print("  idx  guest      name                       type val   inner(self-ref?)")

    for slot in range(80):
        a = inv + slot * STRIDE
        node = bridge._read(a, STRIDE)
        if not node:
            break
        if not (node[0] == 0x10 and node[4] == 0 and node[5] == 0 and node[6] == 0 and node[7] == 0x40):
            print(f"  (fin du pool pattern au slot {slot})")
            break
        a_g = a - CEMU_MEM_BASE
        name = node[8:8+40].split(b"\x00")[0].decode("ascii", "backslashreplace")
        typ = struct.unpack_from(">I", node, 0x20C)[0]
        val = struct.unpack_from(">I", node, 0x214)[0]
        # test auto-reference d'un pointeur interne (+0x64 -> doit etre dans [a_g, a_g+0x220))
        p64 = struct.unpack_from(">I", node, 0x64)[0]
        selfref = "self" if a_g <= p64 < a_g + STRIDE else f"EXT->0x{p64:08X}"
        flag = ""
        if "Fruit" in name or "Apple" in name:
            flag = "  <== APPLE?"
        print(f"  {slot:3d}  0x{a_g:08X} {name:26s} {typ:4d} {val:5d}  {selfref}{flag}")


if __name__ == "__main__":
    main()
