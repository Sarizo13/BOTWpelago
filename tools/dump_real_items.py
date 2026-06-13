"""
Dump cible des VRAIS items (slots peuples) + remonte leur liste jusqu'a la sentinelle,
pour mapper les offsets type/valeur et l'ordre de la liste active.

Lecture seule. Usage (PowerShell admin, Cemu en jeu) :
    python tools/dump_real_items.py
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
POUCH_VTABLE  = 0x1021B5D4
LINK = 0x204


def g2h(g): return g + CEMU_MEM_BASE
def h2g(h): return h - CEMU_MEM_BASE


def name_at(bridge, node_h):
    raw = bridge._read(node_h + 8, 64) or b""
    return raw.split(b"\x00")[0].decode("ascii", errors="backslashreplace")


def hdr(bridge, node_h):
    b = bridge._read(node_h + 0x200, 0x20) or b""
    return [struct.unpack_from(">I", b, i)[0] for i in range(0, len(b), 4)]


def main():
    bridge = CemuMemoryBridge()
    if not bridge.attach() or not bridge.has_live_inventory:
        print("ERREUR attach / inventaire live introuvable.")
        return
    inv = bridge._inv_base
    print(f"inv_base host=0x{inv:012X} guest=0x{h2g(inv):08X}\n")

    # 1) slots 5..28 (vrais items) : nom + en-tete + float +0x54
    print("=== slots 5..28 (occupes) — name | +204next +208prev +20C +210 +214 +218 +21C | f+54 ===")
    for slot in range(5, 29):
        a = inv + slot * _ITEM_STRIDE
        h = hdr(bridge, a)
        f54 = bridge._read(a + 0x54, 4)
        f54v = struct.unpack(">f", f54)[0] if f54 else 0
        nm = name_at(bridge, a)
        print(f"  slot {slot:3d} {nm:26s} "
              f"{h[1]:08X} {h[2]:08X} {h[3]:08X} {h[4]:08X} {h[5]:08X} {h[6]:08X} {h[7]:08X}  f={f54v:g}")

    # 2) remonter la liste du slot 5 via prev (+0x208) jusqu'a sortir du tableau (sentinelle)
    print("\n=== remontee liste depuis slot 5 (via prev +0x208) ===")
    a5 = inv + 5 * _ITEM_STRIDE
    cur_node_g = h2g(a5)
    for step in range(70):
        node_h = g2h(cur_node_g)
        prev = bridge._read(node_h + 0x208, 4)
        if not prev:
            print("  (lecture prev echouee)")
            break
        prev_link = struct.unpack_from(">I", prev, 0)[0]
        prev_node_g = prev_link - LINK
        prev_h = g2h(prev_node_g)
        rel = prev_h - inv
        slot = rel // _ITEM_STRIDE if 0 <= rel < 60 * _ITEM_STRIDE else -1
        # la sentinelle n'a pas le pattern item au +0 ? verifions sa vtable a +0x200 ou +0x0
        vt0 = bridge._read(prev_h, 4)
        vt0v = struct.unpack_from(">I", vt0, 0)[0] if vt0 else 0
        nm = name_at(bridge, prev_h)
        is_sent = (vt0v == POUCH_VTABLE)
        tag = "  <== SENTINELLE?" if is_sent else ""
        print(f"  step {step:2d}: node guest=0x{prev_node_g:08X} slot={slot:3d} vt0=0x{vt0v:08X} name={nm!r:20s}{tag}")
        if is_sent:
            # afficher vtable/next/prev + champs suivants (count/offset) de la sentinelle
            sd = bridge._read(prev_h, 0x20) or b""
            ints = [struct.unpack_from(">I", sd, i)[0] for i in range(0, len(sd), 4)]
            print(f"      sentinel host=0x{prev_h:012X} guest=0x{prev_node_g:08X}")
            print(f"      fields: " + " ".join(f"+{i*4:02X}=0x{v:08X}" for i, v in enumerate(ints)))
            break
        cur_node_g = prev_node_g


if __name__ == "__main__":
    main()
