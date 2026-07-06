"""
activate_tab — TEST (save JETABLE). Rend visible EN LIVE le 1er item d'une catégorie vide en
reproduisant ce que fait updateListHeads() du jeu : insérer une entrée dans mTabs/mTabsType +
mNumTabs++ (structure localisée par diff d'un ramassage naturel, cf. project-live-memory-injection).

Offsets CONSTANTS relatifs à la sentinelle (tête sead::OffsetList = dernier nœud.next-4), membres
fixes de PauseMenuDataMgr (v208) :
  mTabs[50]     sentinelle+0x37CC0   (têtes de page = nœud+4, triées par type croissant)
  mTabsType[50] sentinelle+0x37D88   (type d'onglet ; flèche type2 -> onglet arc 1)
  curseurs      sentinelle+0x37CB8/+0x37CBC   (&mTabs[n-2] / &mTabs[n-1])
  mNumTabs      sentinelle+0x37E5C
  lastItem/Tab  sentinelle+0x37E88/+0x37E8C   (nœud+4 / index icône)

Usage :
  1. Cemu + BotW ; injecte un item d'une catégorie VIDE : python tools/test_item.py Weapon_Shield_018
     (il est dans la liste mais invisible : onglet inexistant).
  2. python tools/activate_tab.py Weapon_Shield_018
  3. Ouvre/ferme l'inventaire → la page bouclier doit apparaître AVEC l'item, SANS reload.
Options : --no-cursors (n'écrit pas les curseurs), --dry (sanity-check seulement, aucune écriture).
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

OFF_MTABS = 0x37CC0
OFF_MTABSTYPE = 0x37D88
OFF_CURSOR_A = 0x37CB8
OFF_CURSOR_B = 0x37CBC
OFF_NUMTABS = 0x37E5C
OFF_LASTITEM = 0x37E88
OFF_LASTTAB = 0x37E8C
NTABS_MAX = 50

# type d'objet -> type d'ONGLET (les flèches type 2 vivent dans l'onglet arc = 1 ; le reste = identité)
def tab_type(t): return 1 if t == 2 else t
# type d'objet -> index d'ICÔNE d'onglet
_ICON = {0: 0, 1: 1, 2: 1, 3: 2, 4: 3, 5: 3, 6: 3, 7: 4, 8: 5, 9: 6}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("actor")
    ap.add_argument("--no-cursors", action="store_true")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché.")
        return
    nodes = b._scan_pouch_nodes()
    base = b._derive_heap_base(nodes) if nodes else None
    if base is None:
        print("ERREUR: base introuvable.")
        return

    # sentinelle = suivant de la queue - 4
    by_next = {n["host"] - base + 0x04: n for n in nodes if n["name"]}
    succ, target = {}, None
    for n in nodes:
        if n["name"]:
            s = by_next.get(struct.unpack_from(">I", n["raw"], 0x04)[0])
            if s is not None:
                succ[id(n)] = s
        if n["name"] == args.actor:
            target = n
    if target is None:
        print(f"ERREUR: {args.actor} absent de la poche (injecte-le d'abord avec test_item.py).")
        return
    tail = None
    for n in nodes:
        if n["name"] and id(n) not in {id(s) for s in succ.values()}:
            cur, seen = n, set()
            while cur is not None and id(cur) not in seen:
                seen.add(id(cur)); tail = cur; cur = succ.get(id(cur))
    sentinel_g = struct.unpack_from(">I", tail["raw"], 0x04)[0] - 0x04
    sh = sentinel_g + base                                    # host de la sentinelle

    def rd(off, k=1):
        raw = b._read(sh + off, 4 * k)
        return [struct.unpack_from(">I", raw, i * 4)[0] for i in range(k)] if raw else None

    numtabs = rd(OFF_NUMTABS)[0]
    mtabs = rd(OFF_MTABS, NTABS_MAX)
    mtypes = rd(OFF_MTABSTYPE, NTABS_MAX)
    node_p4 = {n["host"] - base + 0x04: n for n in nodes if n["name"]}

    # ── SANITY CHECK avant toute écriture ──
    ok = isinstance(numtabs, int) and 1 <= numtabs <= 20
    used_types = mtypes[:numtabs] if ok else []
    if ok:
        ok = all(0 <= t <= 9 for t in used_types) and used_types == sorted(used_types)
        ok = ok and all(mtabs[i] in node_p4 for i in range(numtabs))
    print(f"sentinelle 0x{sentinel_g:08X}  mNumTabs={numtabs}")
    print("mTabs/mTabsType actuels :")
    for i in range(numtabs if ok else 0):
        nm = node_p4[mtabs[i]]["name"] if mtabs[i] in node_p4 else "?"
        print(f"   [{i}] type={mtypes[i]}  -> {nm}")
    if not ok:
        print("SANITY FAIL : offsets mTabs/mTabsType incohérents pour cette version → AUCUNE écriture.")
        return

    tt = tab_type(target["type"])
    if tt in used_types:
        print(f"L'onglet type={tt} existe déjà (catégorie non vide) → rien à faire "
              f"(l'item devrait déjà s'afficher).")
        return
    idx = sum(1 for t in used_types if t < tt)                # position triée
    tgt_p4 = target["host"] - base + 0x04
    print(f"\n→ Insertion onglet type={tt} (icône {_ICON.get(target['type'],'?')}) à l'index {idx} "
          f"pour {args.actor} (nœud+4=0x{tgt_p4:08X}); mNumTabs {numtabs}->{numtabs+1}")
    if args.dry:
        print("(--dry : aucune écriture)")
        return

    n = numtabs
    mtabs_g = sentinel_g + OFF_MTABS
    # décale [idx..n-1] -> [idx+1..n] puis pose la nouvelle entrée
    new_tabs = mtabs[:idx] + [tgt_p4] + mtabs[idx:n] + mtabs[n + 1:]
    new_types = mtypes[:idx] + [tt] + mtypes[idx:n] + mtypes[n + 1:]
    okw = True
    for i in range(idx, n + 1):
        okw &= b._write(sh + OFF_MTABS + i * 4, struct.pack(">I", new_tabs[i]))
        okw &= b._write(sh + OFF_MTABSTYPE + i * 4, struct.pack(">I", new_types[i]))
    okw &= b._write(sh + OFF_NUMTABS, struct.pack(">I", n + 1))
    if not args.no_cursors:
        okw &= b._write(sh + OFF_CURSOR_A, struct.pack(">I", mtabs_g + (n - 1) * 4))
        okw &= b._write(sh + OFF_CURSOR_B, struct.pack(">I", mtabs_g + n * 4))
    okw &= b._write(sh + OFF_LASTITEM, struct.pack(">I", tgt_p4))
    okw &= b._write(sh + OFF_LASTTAB, struct.pack(">I", _ICON.get(target["type"], tt)))
    print(f"[{'OK' if okw else 'ECHEC'}] écritures. Ouvre/ferme l'inventaire pour vérifier.")


if __name__ == "__main__":
    main()
