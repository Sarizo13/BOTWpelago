"""
diag_pouch — diagnostic de l'inventaire live PouchItem.

Affiche la base du tas dérivée, le nombre de nœuds self-ref, et le détail par
nœud (slot, type, value, self-ref). Sert à comprendre pourquoi live_create_item
échoue ("pas d'ancre" / "pas de template").

Usage : python tools/diag_pouch.py
"""
from __future__ import annotations

import os
import struct
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE  # noqa: E402


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
        val = struct.unpack_from(">i", n["raw"], br._NODE_OFF_VAL)[0]
        if sr and n["type"] < 0x20:
            per_type[n["type"]] += 1
        print(f" {n['slot']:>4}  {n['type']:<10} {n['sub']:<6} {val:<7} "
              f"{'oui' if sr else 'non':<7}  {n['name']}")
    print("\nself-ref par type :", dict(sorted(per_type.items())))
    print("types en cache :", sorted(int(k) for k in br._templates))

    # ── Hexdump d'un nœud actif (pomme) pour localiser les vrais offsets ──
    apple = next((n for n in nodes if "Fruit_A" in n["name"]), None) \
        or next((n for n in nodes if n["name"]), None)
    if apple:
        host = apple["host"]
        win = br._read(host - 0x40, 0x2C0) or b""
        print(f"\n=== HEXDUMP nœud '{apple['name']}' @host 0x{host:012X} "
              f"(offsets relatifs au host) ===")
        for off in range(0, len(win), 16):
            rel = off - 0x40
            row = win[off:off + 16]
            hx = " ".join(f"{b:02X}" for b in row)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
            print(f" {rel:+#06x}  {hx:<47}  {asc}")
        # repérer la chaîne de nom dans la fenêtre
        nm = apple["name"].encode("ascii")
        i = win.find(nm)
        print(f"nom '{apple['name']}' trouvé à l'offset relatif "
              f"{i - 0x40:+#x}" if i >= 0 else "nom non trouvé dans la fenêtre")
        # mots de 4 octets valant un petit type (0..9) dans [host, host+0x220)
        body = win[0x40:0x40 + _ITEM_STRIDE]
        smalls = [off for off in range(0, _ITEM_STRIDE, 4)
                  if struct.unpack_from(">I", body, off)[0] < 0x20]
        print("offsets (depuis host) à petite valeur <0x20 :",
              [hex(o) for o in smalls])
    br.detach()


if __name__ == "__main__":
    main()
