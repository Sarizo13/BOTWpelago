"""
Dump live d'un noeud PouchItem (0x220 = 544 octets) depuis la memoire de Cemu, annote
mot par mot (big-endian guest) pour reverser le layout de la liste chainee PauseMenuDataMgr.

But : identifier les pointeurs next/prev de la liste (pour insertion Python d'un nouvel
item) et un eventuel vtable de classe PouchItem (pour retrouver createPorchItem dans Ghidra).

Lecture seule. Usage (PowerShell admin, Cemu en jeu, inventaire avec au moins 1 item) :
    python tools/dump_pouch_node.py
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

CEMU_MEM_BASE = 0x247E4440000  # verifie cette session (guest vaddr -> host = +base)

# Plages guest connues (v208)
RODATA = (0x10000000, 0x10462BBC)
DATA   = (0x10462BC0, 0x104855CC)
BSS    = (0x10485700, 0x105DB1A1)
TEXT   = (0x02000020, 0x04347C2C)


def classify_guest(v):
    if RODATA[0] <= v < RODATA[1]:
        return "rodata(vtable/str)"
    if DATA[0] <= v < DATA[1]:
        return "data"
    if BSS[0] <= v < BSS[1]:
        return "bss"
    if TEXT[0] <= v < TEXT[1]:
        return "text(func)"
    if 0x20000000 <= v < 0xF0000000:
        return "heap?"
    return ""


def dump_node(bridge, node_addr, length=_ITEM_STRIDE, inv_base=None, n_slots=0):
    data = bridge._read(node_addr, length)
    if not data:
        print(f"  (lecture echouee @ 0x{node_addr:012X})")
        return
    print(f"  node host=0x{node_addr:012X}  guest_vaddr=0x{node_addr-CEMU_MEM_BASE:08X}")
    # ascii preview du nom (offset +8 selon le scanner: header 8 octets puis string)
    name = data[8:8+40].split(b"\x00")[0].decode("ascii", errors="backslashreplace")
    print(f"  name(+8): {name!r}")
    for off in range(0, length, 4):
        word = struct.unpack_from(">I", data, off)[0]
        if word == 0:
            continue
        tag = classify_guest(word)
        extra = ""
        # est-ce un pointeur host vers un autre slot du tableau ? (next/prev)
        if inv_base is not None and n_slots:
            lo = inv_base - 0x400
            hi = inv_base + n_slots * _ITEM_STRIDE + 0x400
            if lo <= word <= hi:
                rel = word - inv_base
                slot = rel // _ITEM_STRIDE
                roff = rel % _ITEM_STRIDE
                extra = f"  <== HOST ptr into inv array (slot {slot}, +0x{roff:X})"
            else:
                # pointeur guest converti -> host dans le tableau ?
                gh = word + CEMU_MEM_BASE
                if lo <= gh <= hi:
                    rel = gh - inv_base
                    slot = rel // _ITEM_STRIDE
                    roff = rel % _ITEM_STRIDE
                    extra = f"  <== GUEST ptr -> inv array (slot {slot}, +0x{roff:X})"
        if tag or extra:
            print(f"    +0x{off:03X}: 0x{word:08X}  {tag}{extra}")


def main():
    bridge = CemuMemoryBridge()
    if not bridge.attach():
        print("ERREUR: admin requis / Cemu introuvable / game_data introuvable.")
        return
    print(f"gd_base    = 0x{bridge._gd_base:012X}")
    if not bridge.has_live_inventory:
        print("Inventaire live INTROUVABLE (besoin d'au moins 1 item en poche).")
        return
    inv = bridge._inv_base
    print(f"inv_base   = 0x{inv:012X}  guest_vaddr=0x{inv-CEMU_MEM_BASE:08X}")

    # combien de slots matchent le pattern item ?
    n = 0
    for slot in range(420):
        head = bridge._read(inv + slot * _ITEM_STRIDE, 8)
        if head and head[0] == 16 and head[4] == 0 and head[5] == 0 and head[6] == 0 and head[7] == 64:
            n += 1
        else:
            break
    print(f"slots correspondant au pattern: {n}\n")

    # dump des 3 premiers slots peuples + le 1er slot NON-matchant (free node)
    for slot in range(min(n, 3)):
        print(f"===== SLOT {slot} (peuple) =====")
        dump_node(bridge, inv + slot * _ITEM_STRIDE, inv_base=inv, n_slots=n + 8)
        print()

    print(f"===== SLOT {n} (premier non-matchant / free?) =====")
    dump_node(bridge, inv + n * _ITEM_STRIDE, inv_base=inv, n_slots=n + 8)

    # dump aussi la zone juste AVANT le tableau (la tete de liste / PauseMenuDataMgr ?)
    print(f"\n===== 64 octets AVANT inv_base =====")
    pre = bridge._read(inv - 64, 64)
    if pre:
        for off in range(0, 64, 4):
            word = struct.unpack_from(">I", pre, off)[0]
            if word:
                print(f"    inv-0x{64-off:02X}: 0x{word:08X}  {classify_guest(word)}")


if __name__ == "__main__":
    main()
