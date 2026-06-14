"""
diag_pouch — diagnostic de l'inventaire live PouchItem.

Affiche la base du tas dérivée, le nombre de nœuds self-ref, et le détail par
nœud (slot, type, value, self-ref). Sert à comprendre pourquoi live_create_item
échoue ("pas d'ancre" / "pas de template").

Usage : python tools/diag_pouch.py
"""
from __future__ import annotations

import struct
from collections import Counter

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE


def main() -> None:
    br = CemuMemoryBridge()
    if not br.attach():
        print("Échec attach (Cemu/inventaire introuvable).")
        return
    nodes = br._scan_pouch_nodes()
    print(f"_inv_base = 0x{br._inv_base:012X}")
    print(f"nœuds scannés : {len(nodes)}")
    base = br._derive_heap_base(nodes)
    if base is None:
        print("base du tas : NON dérivable")
        br.detach(); return
    print(f"base du tas dérivée : 0x{base:X}")
    n_sr = br._count_selfref(nodes, base)
    print(f"nœuds self-ref : {n_sr}/{len(nodes)}")

    per_type: Counter = Counter()
    print("\n slot  type        sub     value   selfref  name")
    for n in nodes:
        g = n["host"] - base
        sr = br._node_is_selfref(n["raw"], g)
        val = struct.unpack_from(">i", n["raw"], 0x214)[0]
        if sr and n["type"] < 0x20:
            per_type[n["type"]] += 1
        print(f" {n['slot']:>4}  {n['type']:<10} {n['sub']:<6} {val:<7} "
              f"{'oui' if sr else 'non':<7}  {n['name']}")
    print("\nself-ref par type :", dict(sorted(per_type.items())))
    print("types en cache :", sorted(int(k) for k in br._templates))
    br.detach()


if __name__ == "__main__":
    main()
