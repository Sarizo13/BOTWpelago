"""
Analyse lecture-seule des listes PouchItem live (PauseMenuDataMgr) pour preparer
l'insertion Python d'un nouvel item.

- Trouve les sentinelles de liste (vtable 0x1021B5D4) juste avant inv_base.
- Parcourt chaque liste via next (+0x204), affiche nom + champs d'en-tete de chaque noeud.
- Liste tous les slots du pool (occupes vs libres d'apres le champ nom).

Lecture seule. Usage (PowerShell admin, Cemu en jeu, inventaire non vide) :
    python tools/analyze_pouch_list.py
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
POUCH_VTABLE  = 0x1021B5D4   # vtable de classe PouchItem (a +0x200 du noeud / a la sentinelle)
NODE_LINK_OFF = 0x204        # offset du champ next dans un noeud (prev = +0x208)


def g2h(guest):      # guest vaddr -> host
    return guest + CEMU_MEM_BASE


def h2g(host):       # host -> guest vaddr
    return host - CEMU_MEM_BASE


def read_name(bridge, node_host):
    raw = bridge._read(node_host + 8, 64) or b""
    return raw.split(b"\x00")[0].decode("ascii", errors="backslashreplace")


def main():
    bridge = CemuMemoryBridge()
    if not bridge.attach():
        print("ERREUR: admin requis / Cemu introuvable / game_data introuvable.")
        return
    if not bridge.has_live_inventory:
        print("Inventaire live INTROUVABLE (besoin d'au moins 1 item en poche).")
        return
    inv = bridge._inv_base
    inv_g = h2g(inv)
    print(f"inv_base host=0x{inv:012X}  guest=0x{inv_g:08X}\n")

    # 1) sentinelles de liste : scan [inv-0x400, inv) pour la vtable PouchItem
    print("=== sentinelles candidates (vtable 0x1021B5D4) avant inv_base ===")
    roots = []
    pre = bridge._read(inv - 0x400, 0x400) or b""
    for off in range(0, len(pre) - 4, 4):
        word = struct.unpack_from(">I", pre, off)[0]
        if word == POUCH_VTABLE:
            sent_host = inv - 0x400 + off
            nxt = struct.unpack_from(">I", pre, off + 4)[0] if off + 8 <= len(pre) else 0
            prv = struct.unpack_from(">I", pre, off + 8)[0] if off + 12 <= len(pre) else 0
            roots.append((sent_host, nxt, prv))
            print(f"  sentinel host=0x{sent_host:012X} guest=0x{h2g(sent_host):08X}"
                  f"  next=0x{nxt:08X} prev=0x{prv:08X}")
    print()

    # 2) parcours de chaque liste depuis sa sentinelle
    def node_fields(node_host):
        hdr = bridge._read(node_host + 0x200, 0x20) or b""
        ints = [struct.unpack_from(">I", hdr, i)[0] for i in range(0, len(hdr), 4)]
        return ints

    for si, (sent_host, nxt, prv) in enumerate(roots):
        sent_g = h2g(sent_host)
        print(f"=== LISTE #{si} (sentinel guest 0x{sent_g:08X}) ===")
        # le champ next pointe vers (noeud + NODE_LINK_OFF) ; noeud = next - NODE_LINK_OFF
        cur = nxt
        seen = 0
        while cur and cur != sent_g + 4 and seen < 200:   # sentinelle: son 'next' est a sent+4
            node_g = cur - NODE_LINK_OFF
            node_h = g2h(node_g)
            # validite : doit tomber dans le tableau
            rel = node_h - inv
            slot = rel // _ITEM_STRIDE if 0 <= rel else -1
            name = read_name(bridge, node_h)
            flds = node_fields(node_h)
            fld_str = " ".join(f"{x:08X}" for x in flds[1:7])  # apres la vtable
            print(f"  slot {slot:3d} guest=0x{node_g:08X} name={name!r:24s} hdr[+204..]={fld_str}")
            nxt2 = bridge._read(node_h + NODE_LINK_OFF, 4)
            if not nxt2:
                break
            cur = struct.unpack_from(">I", nxt2, 0)[0]
            seen += 1
        print(f"  ({seen} noeuds)\n")

    # 3) etat du pool : nom de chaque slot
    print("=== pool (slots 0..N) : occupe vs libre ===")
    free, used = [], []
    for slot in range(200):
        addr = inv + slot * _ITEM_STRIDE
        head = bridge._read(addr, 8)
        if not (head and head[0] == 16 and head[4] == 0 and head[5] == 0 and head[6] == 0 and head[7] == 64):
            print(f"  (fin du pool au slot {slot})")
            break
        name = read_name(bridge, addr)
        (used if name else free).append(slot)
    print(f"  occupes (nom non vide): {len(used)} -> {used[:40]}")
    print(f"  libres  (nom vide)    : {len(free)} -> {free[:40]}")


if __name__ == "__main__":
    main()
