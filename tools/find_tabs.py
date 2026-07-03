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

    # nœuds nommés : guest addr -> (name, type)
    guest_of = {}
    for n in nodes:
        if n["name"]:
            guest_of[h2g(n["host"])] = (n["name"], n["type"])
    node_guests = set(guest_of)
    print(f"{len(node_guests)} nœuds nommés. Types présents : "
          f"{sorted({t for _, t in guest_of.values()})}\n")

    # Région de recherche : le buffer PauseMenuDataMgr et large au-delà (mTabs est APRÈS le buffer,
    # mais on scanne tout pour ne rien rater). On note, pour CHAQUE mot de 4 octets, s'il pointe vers
    # le DÉBUT exact d'un nœud connu (mTabs) ou vaut 0 (entrées de page vides en fin de tableau).
    inv0 = b._inv_base - 0x20
    buf_end = inv0 + 420 * _ITEM_STRIDE
    start = inv0
    total = (buf_end - inv0) + 0x10000
    CHUNK = 0x10000
    # map host_addr -> valeur (0 = null, sinon guest pointé si c'est un nœud, else None)
    words: dict[int, int] = {}
    addr, remaining = start, total
    while remaining > 0:
        nrd = min(CHUNK, remaining)
        blob = b._read(addr, nrd)
        if blob:
            for i in range(0, len(blob) - 3, 4):
                v = struct.unpack_from(">I", blob, i)[0]
                if v == 0 or v in node_guests:
                    words[addr + i] = v
        addr += nrd
        remaining -= nrd

    # RUNS : suites d'adresses espacées de 4 où chaque mot est null OU un pointeur-vers-nœud, avec
    # AU MOINS 2 pointeurs-vers-nœud réels dans le run. C'est la signature de mTabs (tableau de têtes
    # de page, souvent suivi de nulls).
    keys = sorted(words)
    runs = []
    i = 0
    while i < len(keys):
        j = i
        while j + 1 < len(keys) and keys[j + 1] - keys[j] == 4:
            j += 1
        run = keys[i:j + 1]
        real = [a for a in run if words[a] in node_guests]
        if len(real) >= 2:
            runs.append(run)
        i = j + 1

    print(f"inv0=0x{inv0:012X}  buf_end=0x{buf_end:012X}\n")
    print(f"── RUNS de pointeurs-de-page (candidats mTabs) : {len(runs)} ──")
    for run in runs:
        head = run[0]
        loc = "APRES-buffer" if head >= buf_end - 0x220 else "dans-buffer"
        real = sum(1 for a in run if words[a] in node_guests)
        print(f"\n  RUN @0x{head:012X} ({loc})  {len(run)} mots, {real} pointeurs réels :")
        for a in run:
            v = words[a]
            if v == 0:
                print(f"     @0x{a:012X}  -> NULL")
            else:
                nm, ty = guest_of[v]
                print(f"     @0x{a:012X}  -> 0x{v:08X}  [{_TYPE_NAME.get(ty,'?'):8s}] {nm}")
        # zone juste après le run = candidat mTabsType (entiers de catégorie) + compteur
        after = run[-1] + 4
        blob = b._read(after, 0x60)
        if blob:
            ints = [struct.unpack_from(">I", blob, k)[0] for k in range(0, 0x60, 4)]
            print(f"     après le run (candidat mTabsType/compteur) : "
                  f"{' '.join(f'{x:08X}' for x in ints)}")


if __name__ == "__main__":
    main()
