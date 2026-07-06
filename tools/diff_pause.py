"""
diff_pause — DIAGNOSTIC (save JETABLE). Capture ce que le jeu modifie dans PauseMenuDataMgr
quand on ajoute le 1ER item d'une catégorie VIDE naturellement (ramassage en jeu). Ce qui
change EN DEHORS du nouveau nœud = le verrou d'affichage de catégorie vide (compteur/bitmask).

Adresses stables tant qu'on ne RECHARGE PAS la save (Cemu ne déplace le heap qu'au reload) →
le before/after se diffe octet à octet.

Procédure (sur save jetable) :
  1. Repère une catégorie VIDE facile à remplir : un ARC (type 1) si tu n'en as aucun, ou une
     tenue, ou un plat. (types présents actuels affichés par find_tabs.)
  2. python tools/diff_pause.py --before        (AVANT le ramassage)
  3. En jeu, RAMASSE le 1er item de cette catégorie vide (ex: un arc). Il s'affiche en live.
     NE RECHARGE PAS la save.
  4. python tools/diff_pause.py --after         (diffe et affiche les changements)

Le rapport met en avant les mots changés HORS de la plage des nœuds = candidats "verrou".
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge, _ITEM_STRIDE  # noqa: E402

SNAP = Path(__file__).resolve().parent / "_pause_before.bin"
META = Path(__file__).resolve().parent / "_pause_before.json"
_TYPE_NAME = {0: "Arme", 1: "Arc", 2: "Fleche", 3: "Bouclier", 4: "ArmTete",
              5: "ArmTorse", 6: "ArmJambe", 7: "Materiau", 8: "Nourri", 9: "ObjCle"}


def _region(b):
    """Retourne (start_host, size, base, sentinel_g, node_guests). Région = tout PauseMenuDataMgr."""
    nodes = b._scan_pouch_nodes()
    base = b._derive_heap_base(nodes) if nodes else None
    if base is None:
        return None
    by_next = {n["host"] - base + 0x04: n for n in nodes if n["name"]}
    succ = {}
    for n in nodes:
        if n["name"]:
            s = by_next.get(struct.unpack_from(">I", n["raw"], 0x04)[0])
            if s is not None:
                succ[id(n)] = s
    tail = None
    for n in nodes:
        if n["name"] and id(n) not in {id(s) for s in succ.values()}:
            cur, seen = n, set()
            while cur is not None and id(cur) not in seen:
                seen.add(id(cur)); tail = cur; cur = succ.get(id(cur))
    if tail is None:
        return None
    sentinel_g = struct.unpack_from(">I", tail["raw"], 0x04)[0] - 0x04
    node_guests = {n["host"] - base: n["type"] for n in nodes if n["name"]}
    start_host = sentinel_g + base - 0x2000
    size = 0x2000 + 420 * _ITEM_STRIDE + 0x10000
    return start_host, size, base, sentinel_g, node_guests


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", action="store_true")
    ap.add_argument("--after", action="store_true")
    ap.add_argument("--dumptabs", action="store_true",
                    help="dump la zone mTabs (sentinelle+0x37A00..+0x38100) annotée")
    args = ap.parse_args()

    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché.")
        return
    reg = _region(b)
    if reg is None:
        print("ERREUR: région PauseMenuDataMgr introuvable.")
        return
    start_host, size, base, sentinel_g, node_guests = reg

    if args.dumptabs:
        # noms des nœuds pour annoter les pointeurs +0x04
        nodes = b._scan_pouch_nodes()
        p4 = {}
        for nn in nodes:
            if nn["name"]:
                g = nn["host"] - base
                p4[g + 0x04] = (nn["name"], nn["type"])
        lo = sentinel_g + base + 0x37A00
        blob = b._read(lo, 0x700)
        if not blob:
            print("ERREUR: lecture échouée.")
            return
        print(f"── mTabs region  [sentinelle+0x37A00 .. +0x38100]  (base 0x{base:012X}) ──")
        for i in range(0, len(blob), 4):
            v = struct.unpack_from(">I", blob, i)[0]
            guest = (lo + i) - base
            off = guest - sentinel_g
            ann = ""
            if v in p4:
                nm, ty = p4[v]
                ann = f"  -> {_TYPE_NAME.get(ty,'?')} {nm} (+4)"
            elif v in node_guests:
                ann = f"  -> {_TYPE_NAME.get(node_guests[v],'?')} (début)"
            elif 0 < v <= 0x40:
                ann = f"  (int {v})"
            elif v == 0xFFFFFFFF:
                ann = "  (-1/vide)"
            print(f"   +0x{off:05X} (guest 0x{guest:08X}): 0x{v:08X}{ann}")
        return

    blob = b._read(start_host, size)
    if not blob:
        print("ERREUR: lecture région échouée.")
        return

    if args.before:
        SNAP.write_bytes(blob)
        META.write_text(json.dumps({"start_host": start_host, "size": size, "base": base,
                                    "sentinel_g": sentinel_g}), encoding="utf-8")
        print(f"[before] {len(blob)} octets snapshotés  (sentinelle guest 0x{sentinel_g:08X}, "
              f"base 0x{base:012X}). RAMASSE l'item en jeu, puis --after.")
        return

    if args.after:
        if not SNAP.is_file():
            print("ERREUR: pas de snapshot --before.")
            return
        meta = json.loads(META.read_text(encoding="utf-8"))
        if meta["base"] != base:
            print(f"ATTENTION: base changée (0x{meta['base']:012X} -> 0x{base:012X}) → la save a "
                  f"été rechargée entre-temps, le diff est invalide. Refais --before.")
            return
        before = SNAP.read_bytes()
        after = blob
        n = min(len(before), len(after))
        gmin = min(node_guests) if node_guests else 0
        gmax = (max(node_guests) + _ITEM_STRIDE) if node_guests else 0
        # indices des mots changés
        idx = [i for i in range(0, n - 3, 4)
               if struct.unpack_from(">I", before, i)[0] != struct.unpack_from(">I", after, i)[0]]
        # REGROUPE en runs contigus (mots changés espacés de ≤ 0x10 = même struct/bloc). Les GROS runs
        # (≥ 12 mots) = textures d'icônes + nouveau nœud (544o) → BRUIT, on jette. Le VERROU = un petit
        # run ISOLÉ (compteur/flag/pointeur) dans une région par ailleurs stable.
        runs = []
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and idx[j + 1] - idx[j] <= 0x10:
                j += 1
            runs.append(idx[i:j + 1])
            i = j + 1
        small = [r for r in runs if len(r) <= 10]
        big = [r for r in runs if len(r) > 10]
        print(f"{len(idx)} mots changés → {len(runs)} runs  ({len(big)} gros=textures/nœud jetés, "
              f"{len(small)} petits runs = candidats VERROU)\n")
        print("── PETITS runs isolés (candidats verrou catégorie) ──")
        for r in small:
            for off_i in r:
                guest = (start_host + off_i) - base
                off = guest - sentinel_g
                sign = "-" if off < 0 else "+"
                bv = struct.unpack_from(">I", before, off_i)[0]
                av = struct.unpack_from(">I", after, off_i)[0]
                note = ""
                d = av - bv
                if -4 <= d <= 4 and d != 0:
                    note += f"  <= {d:+d} (COMPTEUR ?)"
                if av in node_guests or (av - 0x04) in node_guests:
                    note += "  <= pointe vers un nœud"
                if bin(bv ^ av).count("1") <= 3:
                    note += f"  <= {bin(bv ^ av).count('1')} bit(s) (BITMASK ?)"
                print(f"   sentinelle{sign}0x{abs(off):X}  (guest 0x{guest:08X}): "
                      f"0x{bv:08X} -> 0x{av:08X}{note}")
            print()


if __name__ == "__main__":
    main()
