"""
dump_full_node — DIAGNOSTIC (save JETABLE). Dumpe les 544 octets COMPLETS d'un nœud PouchItem
par nom, avec pointeurs NORMALISÉS (self-ref -> SELF+0xNN, vtable -> VT, autre nœud -> NODE) pour
être diffable AVANT/APRÈS un reload (les adresses changent, pas la structure).

But : comparer un nœud re-typé LIVE (arme->bouclier, ne s'affiche pas) au même item reconstruit
par le jeu APRÈS reload (s'affiche) → identifier les champs profonds manquants.

Usage :
  1. Injecte + note l'état : python tools/dump_full_node.py Weapon_Shield_018 > live.txt
  2. Recharge la save en jeu.
  3. python tools/dump_full_node.py Weapon_Shield_018 > reloaded.txt
  4. Colle les DEUX (ou diffe).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python tools/dump_full_node.py <ActorName>")
        return
    name = sys.argv[1]
    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché.")
        return
    nodes = b._scan_pouch_nodes()
    base = b._derive_heap_base(nodes) if nodes else None
    if base is None:
        print("ERREUR: base introuvable.")
        return
    node_starts = {n["host"] - base for n in nodes if n["name"]}
    p4 = {n["host"] - base + 0x04: n["name"] for n in nodes if n["name"]}
    tgt = next((n for n in nodes if n["name"] == name), None)
    if tgt is None:
        print(f"ERREUR: {name} absent de la poche.")
        return
    raw = tgt["raw"]
    ng = tgt["host"] - base                                   # guest du début de nœud
    print(f"── {name}  (nœud guest 0x{ng:08X}, {len(raw)} octets) ──")
    for off in range(0, _ITEM_STRIDE, 4):
        v = struct.unpack_from(">I", raw, off)[0]
        if ng <= v < ng + _ITEM_STRIDE:
            ann = f"SELF+0x{v - ng:03X}"
        elif 0x10000000 <= v < 0x10400000:
            ann = f"VT:{v:08X}"
        elif v in node_starts:
            ann = "->NODE_start"
        elif v in p4:
            ann = f"->NODE+4 ({p4[v]})"
        elif v == 0xFFFFFFFF:
            ann = "-1"
        elif v == 0:
            ann = "."
        else:
            ann = f"0x{v:08X}"
        # n'affiche que les offsets "intéressants" (non nuls) pour alléger, mais garde l'offset
        if ann != ".":
            print(f"   +0x{off:03X}: {ann}")


if __name__ == "__main__":
    main()
