"""
probe_pool — inspecte les slots du tableau PouchItem AU-DELÀ des nœuds actifs,
pour savoir si on peut agrandir le pool (slots zéro/initialisables) ou non.

Usage : python tools/probe_pool.py
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE  # noqa: E402


def main() -> None:
    br = CemuMemoryBridge()
    if not br.attach():
        print("Échec attach.")
        return
    nodes = br._scan_pouch_nodes()
    n_active = len(nodes)
    free = sum(1 for n in nodes if n["type"] == 0xFFFFFFFF)
    print(f"nœuds scannés (motif présent) : {n_active}  | dont libres : {free}")
    print(f"_inv_base = 0x{br._inv_base:012X}  (motif slot0)\n")

    # Examine 30 slots après le dernier nœud actif
    base_motif = br._inv_base
    print(" slot  host           motif?  16 1ers octets               type@0x0C")
    for slot in range(n_active, n_active + 30):
        motif = base_motif + slot * _ITEM_STRIDE
        host = motif - br._NODE_HEADER_OFF
        head = br._read(motif, 8)
        raw = br._read(host, 0x10) or b""
        is_motif = br._matches_item_pattern(head) if head else False
        typ = "?"
        full = br._read(host, _ITEM_STRIDE)
        if full:
            typ = hex(struct.unpack_from(">I", full, br._NODE_OFF_TYPE)[0])
        allzero = full == b"\x00" * _ITEM_STRIDE if full else None
        hexb = " ".join(f"{b:02X}" for b in (raw[:16] if raw else b""))
        tag = "MOTIF" if is_motif else ("ZERO" if allzero else "----")
        print(f" {slot:>4}  0x{host:012X}  {tag:<6} {hexb:<40} {typ}")
    br.detach()


if __name__ == "__main__":
    main()
