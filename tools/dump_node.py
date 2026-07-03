"""
dump_node — DIAGNOSTIC. Attache Cemu et dumpe les octets bruts des nœuds PouchItem d'ÉQUIPEMENT
(armes/arcs/boucliers/armures) pour trouver l'offset du flag "équipé" et la structure exacte.

Usage :
  1. Lance Cemu + BotW, charge ta save, ÉQUIPE une arme (et un bouclier si tu en as un).
  2. python tools/dump_node.py
  3. Colle la sortie ici (dis-moi quelle arme/bouclier est ÉQUIPÉ).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

_TYPE_NAME = {0: "Arme", 1: "Arc", 2: "Fleche", 3: "Bouclier",
              4: "Armure-tete", 5: "Armure-torse", 6: "Armure-jambes",
              7: "Materiau", 8: "Nourriture", 9: "Objet-cle"}


def main() -> None:
    import struct
    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attache (lance le jeu + charge la save).")
        return
    nodes = b._scan_pouch_nodes()
    base = b._derive_heap_base(nodes) if nodes else None
    print(f"{len(nodes)} noeuds scannes.\n")

    # ── ORDRE RÉEL de la liste chaînée (champ next=0x04 → +0x04 du suivant) ──
    if base is not None:
        def h2g(h): return h - base
        by_next = {h2g(n["host"]) + 0x04: n for n in nodes if n["name"]}
        succ = {}
        for n in nodes:
            if not n["name"]:
                continue
            s = by_next.get(struct.unpack_from(">I", n["raw"], 0x04)[0])
            if s is not None:
                succ[id(n)] = s
        # tête = un nœud nommé qui n'est le successeur de personne
        succ_ids = {id(s) for s in succ.values()}
        heads = [n for n in nodes if n["name"] and id(n) not in succ_ids]
        print("── ORDRE LISTE (en suivant next 0x04) ──")
        seen = set()
        tail = None
        for head in heads:
            cur = head
            while cur is not None and id(cur) not in seen:
                seen.add(id(cur))
                print(f"   type={cur['type']} sub={cur['sub']:<3} {cur['name']}")
                tail = cur
                cur = succ.get(id(cur))
        print()

        # ── SENTINELLE (tête sead::OffsetList, dans PauseMenuDataMgr) + zone autour ──
        # On suit next depuis la queue jusqu'à sortir des nœuds → c'est l'adresse sentinelle.
        # On dumpe [sentinelle-0x60 .. +0xC0] : d'éventuels compteurs par catégorie (num boucliers,
        # etc.) qui verrouillent l'affichage d'une catégorie vide y seraient (petits entiers).
        if tail is not None:
            node_bases = {h2g(n["host"]) for n in nodes if n["name"]}
            nxt = struct.unpack_from(">I", tail["raw"], 0x04)[0]
            sentinel_g = nxt - 0x04
            if sentinel_g not in node_bases:
                sh = sentinel_g + base
                print(f"── SENTINELLE @ guest 0x{sentinel_g:08X} (host 0x{sh:012X}) : [-0x60..+0xC0] ──")
                blob = b.read_bytes(sh - 0x60, 0x120) if hasattr(b, "read_bytes") else b._read(sh - 0x60, 0x120)
                if blob:
                    for i in range(0, len(blob), 16):
                        off = i - 0x60
                        sign = "-" if off < 0 else "+"
                        words = " ".join(f"{struct.unpack_from('>I', blob, i+j)[0]:08X}"
                                         for j in range(0, 16, 4) if i + j + 4 <= len(blob))
                        print(f"   {sign}0x{abs(off):03X}: {words}")
                print()

    print("── Octets bruts équipement (types 0-6) ──")
    for n in nodes:
        if not n["name"] or n["type"] > 6:
            continue
        raw = n["raw"][:0x40]
        print(f"[{_TYPE_NAME.get(n['type'],'?'):12s}] type={n['type']} sub={n['sub']} "
              f"name={n['name']}")
        for off in range(0, 0x2C, 4):
            w = struct.unpack_from(">I", raw, off)[0]
            print(f"      +0x{off:02X} = 0x{w:08X} ({w})")
        print()


if __name__ == "__main__":
    main()
