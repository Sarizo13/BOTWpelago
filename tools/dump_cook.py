"""
dump_cook — RE des champs CookData des PouchItem type 8 (nourriture/potions).

Session live : charge une save qui contient DES PLATS À EFFET et/ou DES POTIONS (idéal :
2 plats à effet + 2 potions, valeurs d'effet DIFFÉRENTES), puis :
    python tools/dump_cook.py

Sortie : pour chaque nœud type 8, un dump annoté du header (0x00–0x60) + un balayage des
u32/f32/mots de 0x30 à 0x220. On DIFFE les nœuds entre eux : les offsets où les valeurs
DIFFÈRENT d'un plat à l'autre = les champs CookData (soin en quarts de cœur, EffectType,
EffectLevel, EffectDuration en secondes, SellPrice). Les offsets constants = structure.

Aucune écriture. Objectif : livrer add_porch pour type 8 avec effets (potions/plats).
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from BotWClient.memory_injector import CemuMemoryBridge  # noqa: E402

# Effets de cuisine BotW (EffectType connu — pour reconnaître le champ) :
#  1 Durability 2 Life(max?) 4 LifeRecover? 5 LifeMaxUp 6 ResistHot 7 ResistCold
#  8 ResistElectric 9 Fireproof 10 AttackUp 11 DefenseUp 12 Quietness 13 MovingSpeed
#  14 GutsRecover(endurance) 15 ExGutsMaxUp — valeurs indicatives, à confirmer par le dump.
_KNOWN_EFFECTS = "0..15 (ex: 10=Attaque, 11=Défense, 13=Furtivité/Vitesse, 14/15=Endurance)"


def _f32(raw: bytes, off: int) -> float:
    return struct.unpack_from(">f", raw, off)[0]


def _u32(raw: bytes, off: int) -> int:
    return struct.unpack_from(">I", raw, off)[0]


def _s32(raw: bytes, off: int) -> int:
    return struct.unpack_from(">i", raw, off)[0]


def main() -> None:
    b = CemuMemoryBridge()
    if not b.attach():
        print("ERREUR: Cemu/BotW non attaché (lance le jeu + charge la save).")
        return
    nodes = b._scan_pouch_nodes()
    food = [n for n in nodes if n["type"] == 8]
    print(f"{len(nodes)} nœuds ; {len(food)} de type 8 (nourriture/potion).")
    if not food:
        print("Aucun type 8. Charge une save avec plats/potions en poche.")
        return

    # 1) header annoté de chaque plat
    for n in food:
        raw = n["raw"]
        print(f"\n=== {n['name']}  (slot {n['slot']}, sub={n['sub']}) ===")
        print(f"  type=+0x0C={_u32(raw,0x0C)}  sub=+0x10={_u32(raw,0x10)}  "
              f"value=+0x14={_u32(raw,0x14)}  equip=+0x18={_u32(raw,0x18)}")
        # zone CookData plausible : après le nom (0x28..+64) et les listes sead
        for off in range(0x50, 0x220, 4):
            u = _u32(raw, off)
            if u == 0 or u == 0xFFFFFFFF:
                continue
            f = _f32(raw, off)
            hint = ""
            if 0 < u <= 120:
                hint += " petit-int(soin/level?)"
            if 0.5 < abs(f) < 100000 and (u >> 23) not in (0, 0xFF):
                hint += f" f32={f:.3f}"
            if 30 <= u <= 1800:
                hint += " durée-s?"
            if hint:
                print(f"    +0x{off:03X}: u32={u:<10} s32={_s32(raw,off):<10}{hint}")

    # 2) DIFF entre plats : offsets où ça change = champs CookData
    print("\n=== DIFF entre plats (offsets variables 0x30–0x220) ===")
    diffs = []
    for off in range(0x30, 0x220, 4):
        vals = [_u32(n["raw"], off) for n in food]
        if len(set(vals)) > 1:
            diffs.append((off, vals))
    for off, vals in diffs:
        fvals = [round(_f32(n["raw"], off), 3) for n in food]
        print(f"  +0x{off:03X}: u32{vals}  f32{fvals}")
    print(f"\n{len(diffs)} offset(s) variables — les champs CookData sont parmi eux.")
    print(f"EffectType attendu : {_KNOWN_EFFECTS}")
    print("Repère : soin (petit int, quarts de cœur) ; niveau (1–3) ; durée (30–1800 s) ; "
          "type d'effet (0–15) ; prix de vente.")


if __name__ == "__main__":
    main()
