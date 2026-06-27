"""
verify_singleton — confirme que *(0x10469908) est bien le PauseMenuDataMgr (this de addItem).

Lit le pointeur singleton (guest .data) via le mapping guest->host dérivé de l'inventaire,
puis vérifie la sead::OffsetList du manager : +0x58 = offset intrusif (attendu 4),
+0x50 = tête de liste -> doit pointer vers un nœud (listnode = nœud+0x04).

Usage : python tools/verify_singleton.py
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

SINGLETON_GUEST = 0x10469908   # getter 0x02EAD628 -> *(0x10469908)
LIST_OFF = 0x4c                # sead::OffsetList @ mgr+0x4c (start/end/offset)


def main() -> None:
    br = CemuMemoryBridge()
    if not br.attach():
        print("Échec attach."); return
    nodes = br._scan_pouch_nodes()
    base = br._derive_heap_base(nodes)
    if base is None:
        print("base non dérivable"); br.detach(); return
    print(f"base guest->host = 0x{base:X}")

    def rd32(guest):
        raw = br._read(guest + base, 4)
        return struct.unpack(">I", raw)[0] if raw else None

    mgr = rd32(SINGLETON_GUEST)
    print(f"*(0x{SINGLETON_GUEST:08X}) = manager guest 0x{mgr:08X}" if mgr else "lecture singleton échouée")
    if not mgr:
        br.detach(); return

    # dump de la zone OffsetList présumée du manager
    raw = br._read(mgr + base + 0x40, 0x40)
    if raw:
        print("dump manager+0x40..+0x80 :")
        for o in range(0, 0x40, 0x10):
            row = " ".join(f"{w:08X}" for w in struct.unpack_from(">4I", raw, o))
            print(f"  +0x{0x40+o:03X}:  {row}")

    # nœud ACTIF (type 0..9, nom non vide) -> son prev (node+0x08) doit pointer DANS le manager
    act = next((n for n in nodes if n["name"] and n["type"] < 0x20), None)
    if act:
        ag = act["host"] - base
        nb = br._read(act["host"], 0x10)
        nxt = struct.unpack_from(">I", nb, 0x04)[0]
        prv = struct.unpack_from(">I", nb, 0x08)[0]
        print(f"\nnœud actif '{act['name']}' guest 0x{ag:08X}  next=0x{nxt:08X}  prev=0x{prv:08X}")
        # suit NEXT jusqu'à la sentinelle (listnode dont node+0x00 != vtable PouchItem)
        cur = nxt
        for i in range(2000):
            node = cur - 0x04          # listnode -> node base
            r = br._read(node + base, 0x10)
            if not r:
                print(f"  [{i}] next 0x{cur:08X} illisible -> STOP"); break
            vt = struct.unpack_from(">I", r, 0x00)[0]
            if vt != 0x1021B5D4:        # pas un PouchItem = SENTINELLE (dans le manager)
                mgr_real = cur - 0x4c    # sentinelle OffsetList @ manager+0x4c
                print(f"  [{i}] SENTINELLE @ 0x{cur:08X} -> MANAGER PorchItem ~ 0x{mgr_real:08X}")
                # scan .data pour le global (singleton) qui detient un pointeur dans le manager
                lo, hi = mgr_real - 0x100, cur + 0x10
                print(f"  scan .data pour un pointeur dans [0x{lo:08X},0x{hi:08X}] ...")
                found = []
                gstart = 0x10000000
                blk = 0x600000
                for goff in range(0, blk, 0x40000):
                    chunk = br._read(gstart + goff + base, min(0x40000, blk - goff))
                    if not chunk:
                        continue
                    for k in range(0, len(chunk) - 3, 4):
                        v = struct.unpack_from(">I", chunk, k)[0]
                        if lo <= v <= hi:
                            found.append((gstart + goff + k, v))
                for g, v in found[:12]:
                    print(f"    global 0x{g:08X} = 0x{v:08X}")
                if not found:
                    print("    (aucun global pointant le manager dans 0x10000000-0x10600000)")
                break
            cur = struct.unpack_from(">I", r, 0x04)[0]   # avance next
        else:
            print("  (2000 hops sans sentinelle)")
    br.detach()


if __name__ == "__main__":
    main()
