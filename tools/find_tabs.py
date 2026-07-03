"""
find_tabs — DIAGNOSTIC (save JETABLE). Localise les tableaux mTabs / mTabsType de
PauseMenuDataMgr : ce que BotW reconstruit via updateListHeads() et qui décide quelles
PAGES (donc quelles catégories) s'affichent. Une catégorie à 0 item = 0 page → onglet vide.

Méthode : après le buffer des 420 nœuds PouchItem, on cherche un tableau de POINTEURS qui
visent le DÉBUT de nos nœuds connus (= mTabs = tête de chaque page), et juste après/à côté
un tableau d'ENTIERS = les types de catégorie (mTabsType). On dump les candidats.

Usage :
  1. Cemu + BotW + save chargée (idéalement avec AU MOINS un bouclier déjà présent, pour que
     mTabs contienne une entrée type=3 repérable).
  2. python tools/find_tabs.py
  3. Colle la sortie.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE  # noqa: E402

_TYPE_NAME = {0: "Arme", 1: "Arc", 2: "Fleche", 3: "Bouclier", 4: "ArmTete",
              5: "ArmTorse", 6: "ArmJambe", 7: "Materiau", 8: "Nourri", 9: "ObjCle"}


def main() -> None:
    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché.")
        return
    nodes = b._scan_pouch_nodes()
    base = b._derive_heap_base(nodes) if nodes else None
    if base is None:
        print("ERREUR: base heap introuvable.")
        return

    def h2g(h): return h - base

    # nœuds nommés : guest addr -> (name, type). On indexe le DÉBUT (mTabs) ET +0x04 (liens de liste).
    guest_of = {}
    for n in nodes:
        if n["name"]:
            guest_of[h2g(n["host"])] = (n["name"], n["type"])
    node_guests = set(guest_of)
    plus4 = {g + 0x04: v for g, v in guest_of.items()}      # pointeurs vers la ListNode (+0x04)
    print(f"{len(node_guests)} nœuds nommés. Types présents : "
          f"{sorted({t for _, t in guest_of.values()})}\n")

    # Sentinelle (tête de liste) = suivant de la queue - 0x04 ; borne basse de PauseMenuDataMgr.
    by_next = {h2g(n["host"]) + 0x04: n for n in nodes if n["name"]}
    succ = {}
    for n in nodes:
        if n["name"]:
            s = by_next.get(struct.unpack_from(">I", n["raw"], 0x04)[0])
            if s is not None:
                succ[id(n)] = s
    tail = None
    for n in nodes:
        if n["name"] and id(n) not in {id(s) for s in succ.values()}:
            cur = n
            seen = set()
            while cur is not None and id(cur) not in seen:
                seen.add(id(cur)); tail = cur; cur = succ.get(id(cur))
    sentinel_g = struct.unpack_from(">I", tail["raw"], 0x04)[0] - 0x04 if tail else None
    print(f"sentinelle guest = 0x{sentinel_g:08X}" if sentinel_g else "sentinelle introuvable")

    # Région de recherche : bornée par la sentinelle (début de PauseMenuDataMgr). On couvre en-tête +
    # buffer (420*0x220) + au-delà. On liste TOUS les mots qui pointent vers le DÉBUT d'un nœud (mTabs)
    # ou vers +0x04 (ListNode). Ces pointeurs-vers-début sont RARES hors mTabs → ils ressortiront en cluster.
    if sentinel_g is None:
        return
    lo_host = sentinel_g + base - 0x2000
    span = 0x2000 + 420 * _ITEM_STRIDE + 0x20000
    CHUNK = 0x10000
    starts = []                                  # (host, guest_pointé) pointeurs vers DÉBUT de nœud
    links = []                                   # (host, guest_pointé) pointeurs vers +0x04
    addr, remaining = lo_host, span
    while remaining > 0:
        nrd = min(CHUNK, remaining)
        blob = b._read(addr, nrd)
        if blob:
            for i in range(0, len(blob) - 3, 4):
                v = struct.unpack_from(">I", blob, i)[0]
                if v in node_guests:
                    starts.append((addr + i, v))
                elif v in plus4:
                    links.append((addr + i, v))
        addr += nrd
        remaining -= nrd

    print(f"\n── Pointeurs vers DÉBUT de nœud (candidats mTabs) : {len(starts)} ──")
    prev = None
    for host_addr, v in sorted(starts):
        nm, ty = guest_of[v]
        d = "" if prev is None else f"  Δ=0x{host_addr - prev:X}"
        print(f"   @0x{host_addr:012X} -> 0x{v:08X} [{_TYPE_NAME.get(ty,'?'):8s}] {nm}{d}")
        prev = host_addr

    # Dump autour du plus gros cluster de pointeurs-début (fenêtre couvrant tous les 'starts' proches).
    if starts:
        addrs = sorted(a for a, _ in starts)
        # cluster = plus longue suite de starts espacés de ≤ 0x20
        best_i, best_len = 0, 1
        i = 0
        while i < len(addrs):
            j = i
            while j + 1 < len(addrs) and addrs[j + 1] - addrs[j] <= 0x20:
                j += 1
            if j - i + 1 > best_len:
                best_len, best_i = j - i + 1, i
            i = j + 1
        c0 = addrs[best_i]
        print(f"\n── Dump autour du cluster @0x{c0:012X} ({best_len} pointeurs) : [-0x20..+0x140] ──")
        blob = b._read(c0 - 0x20, 0x160)
        if blob:
            for i in range(0, len(blob), 16):
                off = (c0 - 0x20 + i) - c0
                sign = "-" if off < 0 else "+"
                words_s = " ".join(f"{struct.unpack_from('>I', blob, i+j)[0]:08X}"
                                   for j in range(0, 16, 4) if i + j + 4 <= len(blob))
                print(f"   {sign}0x{abs(off):04X}: {words_s}")


if __name__ == "__main__":
    main()
