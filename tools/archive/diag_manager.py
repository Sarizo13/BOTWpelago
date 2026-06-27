"""
diag_manager — lit les champs du PauseMenuDataMgr qu'addItem déréférence, pour repérer
un pointeur nul/aberrant (cause probable du crash). Cemu doit être VIVANT (jeu chargé).
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

SINGLETON = 0x10469978
ITEMDB = 0x1046CA84
FIELDS = [0x4c, 0x50, 0x58, 0x64, 0x37cec, 0x37d04, 0x37e98, 0x37ca0]


def main() -> None:
    br = CemuMemoryBridge()
    if not br.attach():
        print("attach échec"); return
    nodes = br._scan_pouch_nodes()
    base = br._derive_heap_base(nodes)
    if base is None:
        print("base non dérivable"); br.detach(); return
    print(f"base = 0x{base:X}")

    def rd(guest):
        r = br._read(guest + base, 4)
        return struct.unpack(">I", r)[0] if r else None

    def ok(v):
        return v is not None and (0x10000000 <= v < 0xA0000000)  # pointeur guest plausible

    mgr = rd(SINGLETON)
    print(f"manager *(0x{SINGLETON:08X}) = 0x{mgr:08X}  {'OK' if ok(mgr) else '<<< SUSPECT'}")
    itemdb = rd(ITEMDB)
    print(f"ItemDB  *(0x{ITEMDB:08X}) = 0x{itemdb:08X}  {'OK' if ok(itemdb) else '<<< SUSPECT'}")
    if not mgr:
        br.detach(); return
    for off in FIELDS:
        v = rd(mgr + off)
        tag = ""
        if off in (0x37cec, 0x37d04):   # pointeur-de-pointeur déréférencé en **
            inner = rd(v) if v else None
            tag = f"  -> *={'0x%08X' % inner if inner is not None else '??'}"
        flag = "OK" if (v is not None and (v == 0 or 0x10000000 <= v < 0xA0000000 or v < 0x1000)) else "<<< ?"
        print(f"  mgr+0x{off:05X} = 0x{v:08X}  {flag}{tag}")
    br.detach()


if __name__ == "__main__":
    main()
