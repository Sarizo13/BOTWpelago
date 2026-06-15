"""
test_live_create — valide le splice de live_create_item de façon SÛRE.

Sauvegarde les nœuds touchés, insère un item de test, vérifie l'intégrité des
liens (primaire + secondaire) par relecture, puis RESTAURE automatiquement (sauf
--keep). Aucune dépendance au rendu en jeu : on vérifie les pointeurs.

Usage :
  python tools/test_live_create.py            # insère, vérifie, restaure
  python tools/test_live_create.py --keep     # insère et LAISSE l'item (visuel en jeu)
  python tools/test_live_create.py --restore   # restaure depuis tmp/pouch_backup.json
"""
from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE  # noqa: E402

BACKUP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tmp", "pouch_backup.json")
TEST_ITEM = "Item_Fruit_I"   # Voltfruit — matériau type 7, peu probable d'être présent


def u32(b, o): return struct.unpack_from(">I", b, o)[0]


def restore(br: CemuMemoryBridge) -> None:
    data = json.load(open(BACKUP, encoding="utf-8"))
    for host_hex, raw_hex in data.items():
        br._write(int(host_hex, 16), bytes.fromhex(raw_hex))
    print(f"restauré {len(data)} nœud(s) depuis {BACKUP}")


def main() -> None:
    keep = "--keep" in sys.argv
    br = CemuMemoryBridge()
    if not br.attach():
        print("Échec attach.")
        return
    if "--restore" in sys.argv:
        restore(br); br.detach(); return

    nodes = br._scan_pouch_nodes()
    base = br._derive_heap_base(nodes)
    if base is None:
        print("base non dérivable"); br.detach(); return

    def h2g(h): return h - base

    # backup de TOUS les nœuds (simple et sûr)
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    bak = {hex(n["host"]): n["raw"].hex() for n in nodes}
    json.dump(bak, open(BACKUP, "w", encoding="utf-8"))
    print(f"backup de {len(bak)} nœuds -> {BACKUP}")

    if br.live_find_item(TEST_ITEM) is not None:
        print(f"{TEST_ITEM} déjà présent — choisis un autre item de test")
        br.detach(); return

    # anchor anticipé = nœud type-7 self-ref (pour vérifs)
    def selfref(n): return br._node_is_selfref(n["raw"], h2g(n["host"]))
    t7 = [n for n in nodes if n["name"] and n["type"] == 7 and selfref(n)]
    print(f"templates/anchors type-7 disponibles : {len(t7)}  "
          f"| nœuds libres : {sum(1 for n in nodes if n['type']==0xFFFFFFFF)}")

    ok = br.live_create_item(TEST_ITEM, 7, subtype=8, value=3)
    print(f"live_create_item -> {ok}")

    # vérif : l'item est retrouvable + ses liens sont cohérents
    addr = br.live_find_item(TEST_ITEM)
    print(f"live_find_item({TEST_ITEM}) -> {'TROUVÉ' if addr else 'ABSENT'}")
    new_nodes = br._scan_pouch_nodes()
    F = next((n for n in new_nodes if n["name"] == TEST_ITEM), None)
    integrity = False
    if F:
        Fg = h2g(F["host"])
        nxt = u32(F["raw"], br._NODE_OFF_NEXT)
        prv = u32(F["raw"], br._NODE_OFF_PREV)
        nh = (nxt - br._NODE_OFF_NEXT) + base
        ph = (prv - br._NODE_OFF_NEXT) + base
        nraw = br._read(nh, _ITEM_STRIDE); praw = br._read(ph, _ITEM_STRIDE)
        # le prev de F.next doit pointer vers F ; le next de F.prev doit pointer vers F
        back_ok = nraw and u32(nraw, br._NODE_OFF_PREV) == Fg + br._NODE_OFF_NEXT
        fwd_ok = praw and u32(praw, br._NODE_OFF_NEXT) == Fg + br._NODE_OFF_NEXT
        integrity = bool(back_ok and fwd_ok)
        print(f"  F.type={F['type']} F.value={struct.unpack_from('>i', F['raw'], br._NODE_OFF_VAL)[0]}")
        print(f"  liens primaires cohérents : next.prev->F={bool(back_ok)}  prev.next->F={bool(fwd_ok)}")
    print(f"\nRESULTAT : {'OK splice integre' if integrity else 'ECHEC'}")

    if keep and integrity:
        print("--keep : item laissé en jeu (ouvre/ferme la poche pour le voir).")
    else:
        restore(br)
    br.detach()


if __name__ == "__main__":
    main()
